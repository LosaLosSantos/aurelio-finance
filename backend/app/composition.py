"""ETF look-through composition: countries, sectors, top holdings per symbol.

Answers "what is REALLY inside this portfolio?" — three MSCI-World-like ETFs
look diversified but may add up to ~65% US / ~30% tech. Sources (all free,
verified 2026-08-20):

0. The ISSUER's own file (app/issuers.py) when one covers the fund: every
   position, not a top ten — the only source that makes cross-fund overlap
   correct rather than merely indicative.
1. justETF (scraping package) covers the rest: natively ISIN-keyed, curated
   for UCITS, but only the top ten holdings.
2. Trackinsight (free JSON, no auth) covers funds by ticker, so it works when
   no ISIN is known — countries, sectors, top holdings and a holding count.
3. yfinance funds_data is the last-resort fallback (sectors + top-10 only).

Morningstar (mstarpy) was REMOVED from this path: since v10 it bootstraps its
session by opening a real browser window, which in a local desktop app means
clicking "update" launches morningstar.com in your face. No data source is
worth that. Everything here is a plain HTTP call.

An ISIN is what unlocks the best source, and a Yahoo ticker is what prices a
position — they are different jobs, so a holding carries both fields rather
than overloading one.

Every network call lives in a `_fetch_*` helper so tests monkeypatch them.
Results are cached in the DB (composition_cache) for CACHE_TTL_DAYS days;
`refresh=True` bypasses the TTL. All percentages are 0-100.
"""

from __future__ import annotations

import datetime
import json
import logging
import re

from sqlalchemy.orm import Session

from app import crud, fx, geo, issuers, models, positions, prices

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 15
# A result missing the country axis came from the last-resort source (Yahoo has
# no geography). Cache it BRIEFLY: a transient failure of justETF/Morningstar
# must not freeze a degraded view for two weeks — that is exactly how a blip
# turned into "the look-through has no countries" for days.
PARTIAL_TTL_DAYS = 1
# How much of Trackinsight's holdings file we keep — and ONLY Trackinsight's.
# The issuer path publishes every position and keeps every position, which is
# the whole reason it sits first in the waterfall; justETF publishes a top ten
# and we keep the ten. Named for its one caller, because read as a global
# policy it invites someone to "apply it consistently", and applying it to the
# issuer would throw away the only complete holdings list in the app.
TRACKINSIGHT_TOP_HOLDINGS = 25

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


class CompositionError(Exception):
    """Raised when a symbol's composition cannot be resolved from any source."""


class Undecomposable(CompositionError):
    """Nothing can place this instrument — an answer, not a failure.

    A subclass so every existing `except CompositionError` keeps working;
    callers that care about the difference (the cache does) can now ask for
    it. Crypto and a few listings have no holdings file anywhere and never
    will, and that is a stable fact worth remembering rather than a transient
    error worth retrying. It carries every source's refusal, because "nobody
    could place it" is only useful next to WHY nobody could."""

    def __init__(self, symbol: str, errors: list[str] | None = None) -> None:
        reasons = " · ".join(errors or []) or "no reason was reported"
        super().__init__(f"Nothing can decompose '{symbol}': {reasons}")
        self.symbol = symbol
        self.errors = list(errors or [])


# The `source` of a cache row that holds one of the above. It is a real row
# with real (empty) axes, so `_ttl_for` gives it the short TTL on its own.
UNDECOMPOSABLE = "undecomposable"


def _base_ticker(symbol: str) -> str:
    """Strip the Yahoo exchange suffix: 'VWCE.MI' -> 'VWCE'."""
    return symbol.split(".")[0].strip().upper()


def is_isin(text: str) -> bool:
    return bool(_ISIN_RE.match((text or "").strip().upper()))


# --- Network fetchers (monkeypatched in tests) ------------------------------


TRACKINSIGHT_URL = "https://data.trackinsight.com"

# The justETF screener is one download of ~4.5k UCITS funds; hold it in memory
# for a day rather than fetching it per symbol.
_CATALOGUE: dict | None = None
_CATALOGUE_AT: datetime.datetime | None = None
CATALOGUE_TTL_HOURS = 24


def _justetf_catalogue() -> dict[str, str]:
    """{ticker: isin} for every UCITS ETF justETF lists. Network call, cached."""
    global _CATALOGUE, _CATALOGUE_AT
    now = datetime.datetime.now(datetime.timezone.utc)
    if (
        _CATALOGUE is not None
        and _CATALOGUE_AT is not None
        and (now - _CATALOGUE_AT) <= datetime.timedelta(hours=CATALOGUE_TTL_HOURS)
    ):
        return _CATALOGUE
    import justetf_scraping

    df = justetf_scraping.load_overview()
    _CATALOGUE = {
        str(t).strip().upper(): str(isin)
        for isin, t in df["ticker"].items()
        if isinstance(t, str) and t.strip()
    }
    _CATALOGUE_AT = now
    return _CATALOGUE


def _fetch_trackinsight_isin(ticker: str) -> str | None:
    """The fund's ISIN from Trackinsight's free fund file. Network call."""
    import httpx

    resp = httpx.get(f"{TRACKINSIGHT_URL}/funds/{ticker}.json", timeout=15)
    resp.raise_for_status()
    return resp.json().get("isin") or None


def _fetch_trackinsight(ticker: str) -> dict:
    """Trackinsight's free holdings file: countries, sectors, top holdings and
    the real holding count, keyed by ticker so it needs no ISIN. Weights come
    as fractions. Network call; raises on any failure."""
    import httpx

    resp = httpx.get(f"{TRACKINSIGHT_URL}/holdings/{ticker}.json", timeout=20)
    resp.raise_for_status()
    d = resp.json()
    out = {
        "name": None,
        "countries": [
            {"name": k, "pct": round(float(v.get("weight", 0)) * 100, 2)}
            for k, v in (d.get("countries") or {}).items()
            if v.get("weight")
        ],
        "sectors": [
            {"name": k, "pct": round(float(v.get("weight", 0)) * 100, 2)}
            for k, v in (d.get("sectors") or {}).items()
            if v.get("weight")
        ],
        "top_holdings": [
            {"name": h["label"], "pct": round(float(h.get("weight", 0)) * 100, 3), "isin": None}
            for h in (d.get("topHoldings") or [])[:TRACKINSIGHT_TOP_HOLDINGS]
            if h.get("label")
        ],
        "holdings_count": d.get("count"),
    }
    out["countries"].sort(key=lambda x: x["pct"], reverse=True)
    out["sectors"].sort(key=lambda x: x["pct"], reverse=True)
    if not (out["countries"] or out["sectors"]):
        raise CompositionError(f"Trackinsight has no composition for '{ticker}'")
    return out


def _fetch_issuer(isin: str) -> dict:
    """The fund's full holdings from its issuer. Network call; raises."""
    return issuers.fetch(isin)


def _fetch_justetf(isin: str) -> dict:
    """justETF profile for an ISIN: {name, countries, sectors, top_holdings}.
    Network call; raises on any failure."""
    import justetf_scraping

    o = justetf_scraping.get_etf_overview(isin, expand_allocations=True)
    out = {
        "name": o.get("name"),
        "countries": [
            {"name": c["name"], "pct": round(float(c["percentage"]), 2)}
            for c in (o.get("countries") or [])
        ],
        "sectors": [
            {"name": s["name"], "pct": round(float(s["percentage"]), 2)}
            for s in (o.get("sectors") or [])
        ],
        "top_holdings": [
            {
                "name": h["name"],
                "pct": round(float(h["percentage"]), 3),
                "isin": h.get("isin"),
            }
            for h in (o.get("top_holdings") or [])
        ],
    }
    if not (out["countries"] or out["sectors"]):
        raise CompositionError(f"justETF has no allocations for {isin}")
    return out


# Yahoo names its 11 sectors its own way; the issuers (and everyone else in
# finance) use GICS. They map one-to-one, but as raw strings they do not match,
# so "Technology 13.6%" and "Information Technology 12.8%" appeared as two
# different sectors — the same fragility that once lost Microsoft from the
# overlap, one level up. Canonical form is GICS, because it is the standard the
# authoritative sources publish in.
_SECTOR_ALIASES = {
    "technology": "Information Technology",
    "informationtechnology": "Information Technology",
    "financialservices": "Financials",
    "financial": "Financials",
    "financials": "Financials",
    "healthcare": "Health Care",
    "consumercyclical": "Consumer Discretionary",
    "consumerdiscretionary": "Consumer Discretionary",
    "consumerdefensive": "Consumer Staples",
    "consumerstaples": "Consumer Staples",
    "basicmaterials": "Materials",
    "materials": "Materials",
    "industrials": "Industrials",
    "energy": "Energy",
    "realestate": "Real Estate",
    "utilities": "Utilities",
    "communicationservices": "Communication Services",
    "communication": "Communication Services",
    "telecommunications": "Communication Services",
    "telecommunicationservices": "Communication Services",
}


def _canonical_sector(name: str) -> str:
    """One name per sector, whatever the source called it. Unknown labels pass
    through untouched: a bond fund's "Treasury" is a real category, not a
    misspelt equity sector, and inventing a mapping for it would be worse than
    leaving it alone."""
    key = re.sub(r"[^a-z]", "", (name or "").lower())
    return _SECTOR_ALIASES.get(key, name)


def _fetch_equity_profile(symbol: str) -> dict | None:
    """A single share's own profile: {name, country, sector}, or None if the
    instrument is not a plain share. Network call.

    A direct equity has no holdings file to look inside, and never will — but
    it does not need one: a share of Apple *is* 100% United States and 100%
    Technology. Treating it as undecomposable put half a portfolio behind a
    "no data" bar that had data all along. `quoteType` is the discriminator
    Yahoo itself uses: 'EQUITY' for a share, 'ETF'/'MUTUALFUND' for a fund
    (which returns no country or sector of its own, precisely because its
    exposure lives in its holdings)."""
    import yfinance as yf

    info = yf.Ticker(symbol).get_info() or {}
    if (info.get("quoteType") or "").upper() != "EQUITY":
        return None
    country, sector = info.get("country"), info.get("sector")
    if not (country or sector):
        return None  # a share we cannot place is no better than a fund we cannot open
    return {
        "name": info.get("longName") or info.get("shortName"),
        "country": country,
        "sector": sector,
    }


def _fetch_yf_sectors(symbol: str) -> dict:
    """yfinance funds_data fallback: {sectors, top_holdings} (no countries).
    Network call; raises on any failure."""
    import yfinance as yf

    fd = yf.Ticker(symbol).funds_data
    sectors = fd.sector_weightings or {}
    top = fd.top_holdings
    out = {
        "sectors": [
            {"name": _humanize(k), "pct": round(float(v) * 100, 2)}
            for k, v in sectors.items()
            if v
        ],
        "top_holdings": [
            {"name": str(r["Name"]), "pct": round(float(r["Holding Percent"]) * 100, 3), "isin": None}
            for _, r in top.iterrows()
        ]
        if top is not None and len(top)
        else [],
    }
    if not (out["sectors"] or out["top_holdings"]):
        raise CompositionError(f"Yahoo has no fund data for '{symbol}'")
    return out


_LEGAL_SUFFIXES = {
    "INC", "CORP", "CORPORATION", "PLC", "LTD", "LIMITED", "LLC", "CO",
    "COMPANY", "SA", "AG", "NV", "SE", "AB", "ASA", "OYJ", "SPA", "&",
    # REGS is not a legal form but it behaves like one here: a bond ETF lists
    # "Italy (Republic Of)" and "Italy (Republic Of) Regs" as two holdings, and
    # they are one issuer offering under two regulations. On an axis that asks
    # how much of the portfolio one name accounts for, they are the same name.
    "REGS",
}


def _company_key(name: str) -> str:
    """A stable key for the same company written by two different issuers.

    iShares publishes "NVIDIA CORP", Vanguard "NVIDIA Corp" — the same holding
    in two files, and a raw string match silently treats them as two different
    companies, which is precisely how the largest position in the portfolio
    fell out of the overlap list. Uppercase, drop punctuation and the legal
    form, and they meet. Share classes are deliberately NOT merged: Alphabet A
    and C are different lines and the reader should see them as such."""
    cleaned = re.sub(r"[^A-Z0-9 ]+", " ", (name or "").upper())
    words = [w for w in cleaned.split() if w and w not in _LEGAL_SUFFIXES]
    return " ".join(words) or (name or "").upper()


def _humanize(key: str) -> str:
    """'unitedStates' / 'consumer_cyclical' -> 'United States' / 'Consumer Cyclical'."""
    key = key.replace("_", " ")
    key = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key)
    return key.strip().title()


# --- Cache + waterfall ------------------------------------------------------


def _is_fresh(
    fetched_at: str, ttl_days: int = CACHE_TTL_DAYS, now: datetime.datetime | None = None
) -> bool:
    try:
        ts = datetime.datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    return (now - ts) <= datetime.timedelta(days=ttl_days)


def _ttl_for(row: models.CompositionCache) -> int:
    """Full TTL for a complete result; the short one when the country axis is
    missing, so a degraded entry gets retried the next day."""
    try:
        complete = bool(json.loads(row.data).get("countries"))
    except (ValueError, TypeError):
        complete = False
    return CACHE_TTL_DAYS if complete else PARTIAL_TTL_DAYS


def _poorer(result: dict, cached: models.CompositionCache) -> str | None:
    """Why a fetched composition is poorer than the cached one, or None.

    Poorer is one of two things. The fetch falls from a source that lists every
    holding (`_COMPLETE_HOLDINGS`: the issuer's file, a share that is its own
    holding) to one that publishes an extract (justETF, Trackinsight, Yahoo).
    Or it lost an axis the cache had: countries or sectors. Within one class a
    fetch always replaces the cache, and nothing is counted: an issuer's own
    file can list a few dozen fewer holdings weeks later, a real update with
    fewer rows that a count would refuse."""
    if cached.source in _COMPLETE_HOLDINGS and result["source"] not in _COMPLETE_HOLDINGS:
        return f"{result['source']} publishes an extract, the cache holds every holding from {cached.source}"
    try:
        kept = json.loads(cached.data)
    except (ValueError, TypeError):
        return None
    for axis in ("countries", "sectors"):
        if kept.get(axis) and not result.get(axis):
            return f"this fetch lost the {axis} axis"
    return None


def get_composition(
    db: Session, symbol: str, refresh: bool = False, isin: str | None = None
) -> dict:
    """The composition for a holding's symbol, from cache when fresh (15 days)
    or from the source waterfall otherwise. A direct share resolves to itself
    (100% one country, one sector); Undecomposable is raised when nothing can
    place the instrument at all (e.g. crypto).

    That refusal is cached too, and raised again from the cache. It is an
    answer like any other and costs the whole waterfall to reach, so throwing
    it away meant paying for it on every page load for as long as the position
    was held."""
    symbol = (symbol or "").strip()
    if not symbol:
        raise CompositionError("Empty symbol")

    cached = crud.get_composition_cache(db, symbol)
    # A refresh refused as poorer less than PARTIAL_TTL_DAYS ago is not tried
    # again yet: the kept entry serves, stale or not, and says how old it is.
    refused_lately = (
        cached is not None
        and cached.refused_at is not None
        and _is_fresh(cached.refused_at, PARTIAL_TTL_DAYS)
    )
    if cached is not None and not refresh and (
        _is_fresh(cached.fetched_at, _ttl_for(cached)) or refused_lately
    ):
        if cached.source != UNDECOMPOSABLE:
            return _row_to_dict(cached)
        # Still the same answer, and still raised rather than returned: nothing
        # downstream has to learn a second shape for the same fact.
        #
        # Unless the caller now brings the one thing that was missing. That
        # refusal usually ends with "Add the fund's ISIN to this holding to
        # unlock the country breakdown" — ignoring the ISIN for a day after the
        # user adds it would make a liar of the instruction.
        given = (isin or "").strip().upper()
        if not given or given == (cached.isin or "").strip().upper():
            raise Undecomposable(symbol, _errors_in(cached))

    try:
        result = _resolve_and_fetch(symbol, isin)
    except CompositionError as exc:
        # Stale data beats no data — unless the stale row IS this same refusal,
        # which has nothing to serve and only needs its date moved on.
        if cached is not None and cached.source != UNDECOMPOSABLE:
            return _row_to_dict(cached)
        # "Nobody can place this" and "nobody answered" are different claims,
        # and only the first is worth remembering. Asked the same way prices.py
        # asks it — probe something that is always quoted — because writing an
        # outage into the cache as a property of the instrument is how a blip
        # becomes a fact for as long as the entry lives.
        if prices.market_reachable():
            _remember_that_nothing_answered(db, symbol, isin, exc)
        raise

    # A fetch poorer than the cached entry (`_poorer` says what poorer is) does
    # not replace it. The entry keeps its data and its fetched_at; the refusal
    # goes in refused_at, so the next attempt waits PARTIAL_TTL_DAYS instead of
    # running the waterfall on every page load. `refresh=True` still tries.
    if cached is not None:
        why = _poorer(result, cached)
        if why:
            logger.warning(
                "Keeping the cached composition for %s: %s (%s)",
                symbol,
                why,
                "; ".join(result.get("errors") or ["no reason reported"]),
            )
            crud.note_refused_refresh(db, cached)
            return _row_to_dict(cached)

    row = crud.upsert_composition_cache(
        db,
        symbol=symbol,
        isin=result.get("isin"),
        resolved_name=result.get("name"),
        source=result["source"],
        data=json.dumps(
            {
                "countries": result["countries"],
                "sectors": result["sectors"],
                "top_holdings": result["top_holdings"],
                "holdings_count": result.get("holdings_count"),
                # Why the richer sources did not answer, kept so the UI can say
                # so instead of just showing an axis that looks empty.
                "errors": result.get("errors") or [],
            }
        ),
    )
    return _row_to_dict(row)


def _remember_that_nothing_answered(
    db: Session, symbol: str, isin: str | None, exc: CompositionError
) -> None:
    """Cache the negative result, with the reasons every source gave.

    Reaching "nothing can decompose this" costs the entire waterfall: three
    network sources behind 15s and 20s timeouts. The cache stored successes
    only, so that price was paid again on every single page load — one crypto
    position was 12.56s of a look-through that was otherwise 0.00s per symbol
    from cache. The negative is as much of a result as the positive.

    Its TTL is not chosen here, and deliberately so: the row has no countries,
    which is exactly what `_ttl_for` already reads to hand out PARTIAL_TTL_DAYS
    instead of the full fifteen. That is the right length for the same reason
    it is right for a degraded answer — this one is stable, but not permanent.
    A fund gains an issuer adapter, a holding gains its ISIN, Trackinsight
    starts covering a ticker. One day means the waterfall runs once and picks
    any of that up tomorrow, rather than on every page load or not for a
    fortnight.
    """
    crud.upsert_composition_cache(
        db,
        symbol=symbol,
        isin=isin,
        resolved_name=None,
        source=UNDECOMPOSABLE,
        data=json.dumps(
            {
                "countries": [],
                "sectors": [],
                "top_holdings": [],
                "holdings_count": None,
                "errors": list(getattr(exc, "errors", None) or [str(exc)]),
            }
        ),
    )


def _resolve_and_fetch(symbol: str, isin: str | None = None) -> dict:
    """The waterfall, all plain HTTP: an ISIN (given, or resolved from the
    ticker) unlocks justETF, which owns the country/sector axes; Trackinsight
    covers funds by ticker when no ISIN is available; yfinance closes the gap
    with sectors alone."""
    errors: list[str] = []

    # Ask what the instrument IS before assuming it is a fund. A direct share
    # can only fail the waterfall below — three doomed network round-trips
    # ending in an exception that used to take the whole endpoint down with it
    # — and it resolves to itself for free: one country, one sector, 100%.
    if not is_isin(symbol):
        try:
            equity = _fetch_equity_profile(symbol)
        except Exception as exc:
            equity = None
            logger.info("%s profile lookup failed: %s: %s", symbol, type(exc).__name__, exc)
        if equity is not None:
            name = equity["name"] or symbol
            return {
                "errors": errors,
                "source": "equity",
                "isin": isin,
                "name": name,
                "countries": (
                    [{"name": equity["country"], "pct": 100.0}] if equity["country"] else []
                ),
                "sectors": (
                    [{"name": equity["sector"], "pct": 100.0}] if equity["sector"] else []
                ),
                # Its own single holding, so it lands in the overlap alongside
                # the same company held inside the funds: that sum is the X-Ray.
                "top_holdings": [{"name": name, "pct": 100.0, "isin": isin}],
                "holdings_count": 1,
            }

    isin = (isin or "").strip().upper() or (symbol.upper() if is_isin(symbol) else None)
    if not isin:
        isin = _resolve_isin(_base_ticker(symbol), errors)

    # The issuer first: it publishes every position, so the axes and the
    # overlap come from the real portfolio instead of a published top ten.
    if isin:
        try:
            data = _fetch_issuer(isin)
            return {"errors": errors, "source": "issuer", "isin": isin, **data}
        except Exception as exc:
            msg = f"Issuer: {type(exc).__name__}: {exc}"
            logger.info("%s (%s) has no issuer adapter: %s", symbol, isin, msg)
            errors.append(msg)

    justetf: dict | None = None
    if isin:
        try:
            justetf = _fetch_justetf(isin)
        except Exception as exc:
            msg = f"justETF: {type(exc).__name__}: {exc}"
            logger.warning("%s (%s) lookup failed: %s", symbol, isin, msg)
            errors.append(msg)
    if justetf is not None:
        return {
            "errors": errors,
            "source": "justetf",
            "isin": isin,
            "name": justetf.get("name"),
            "countries": justetf["countries"],
            "sectors": justetf["sectors"],
            "top_holdings": justetf["top_holdings"],
            "holdings_count": justetf.get("holdings_count"),
        }

    try:
        ti = _fetch_trackinsight(_base_ticker(symbol))
        return {"errors": errors, "source": "trackinsight", "isin": isin or ti.get("isin"), **ti}
    except Exception as exc:
        msg = f"Trackinsight: {type(exc).__name__}: {exc}"
        logger.warning("%s lookup failed: %s", symbol, msg)
        errors.append(msg)

    try:
        yf_data = _fetch_yf_sectors(symbol)
    except Exception as exc:
        # `except Exception`, like every other step of this waterfall, and for
        # the same reason: yfinance answers "this is not a fund" by raising its
        # own YFDataException, not the CompositionError this call site used to
        # expect. That one leak is why BTC-EUR never reached the code below —
        # it went straight past the whole cache and out to the caller.
        #
        # Every source has now refused, which is an ANSWER. It leaves here
        # carrying all of them, so the caller can store the negative WITH its
        # reasons instead of only the last one to speak.
        errors.append(f"Yahoo: {type(exc).__name__}: {exc}")
        raise Undecomposable(symbol, errors) from exc
    return {
        "errors": errors,
        "source": "yfinance",
        "isin": isin,
        "name": None,
        "countries": [],
        "holdings_count": None,
        **yf_data,
    }


def _resolve_isin(ticker: str, errors: list[str]) -> str | None:
    """Ticker -> ISIN without a browser. justETF's screener is tried first
    (it is the same catalogue the profile pages come from), then Trackinsight.
    A miss is normal: alternative listings carry their own ticker (Milan's
    MVOL is Xetra's IQQ0 in the screener), which is exactly why a holding can
    carry its ISIN explicitly, and why a miss ends by saying so."""
    try:
        row = _justetf_catalogue().get(ticker)
        if row:
            return row
    except Exception as exc:
        errors.append(f"justETF catalogue: {type(exc).__name__}: {exc}")
    try:
        found = _fetch_trackinsight_isin(ticker)
        if found:
            return found
    except Exception:
        pass
    # Only a FOUND ISIN returns early. Trackinsight says "that fund file has no
    # ISIN" by handing back None rather than raising, and returning that None
    # straight out skipped the remedy below — leaving the user an empty country
    # axis with no reason and nothing to do about it. The refusal can now be
    # cached, and adding the ISIN is the documented way out of a cached one, so
    # this is the one sentence that must survive the trip.
    errors.append(
        f"No ISIN found for '{ticker}'. Add the fund's ISIN to this holding to "
        "unlock the country breakdown."
    )
    return None


def _row_to_dict(row: models.CompositionCache) -> dict:
    data = json.loads(row.data)
    return {
        "symbol": row.symbol,
        "isin": row.isin,
        "name": row.resolved_name,
        "source": row.source,
        "fetched_at": row.fetched_at,
        "countries": data.get("countries") or [],
        "sectors": data.get("sectors") or [],
        "top_holdings": data.get("top_holdings") or [],
        "holdings_count": data.get("holdings_count"),
        "errors": data.get("errors") or [],
    }


# Which sources hand back a fund's WHOLE holdings list. The issuer publishes
# every position it holds; a directly held share is its own single holding,
# which is complete by definition. Everything else is a published extract —
# justETF's top ten, Trackinsight's file cut to TRACKINSIGHT_TOP_HOLDINGS,
# Yahoo's top ten — however faithfully we keep what we were handed.
_COMPLETE_HOLDINGS = frozenset({"issuer", "equity"})


# --- Portfolio-level aggregation --------------------------------------------


def _lookup_key(p) -> str | None:
    """What the look-through fetches a position by: its ticker, or, with none,
    its ISIN. The ISIN is what the issuer files and justETF key on anyway; a
    ticker's only job in the waterfall is to resolve one when none is given,
    so a position that already carries it was being skipped for lacking the
    thing that finds it. Anything not shaped like an ISIN is not a key."""
    if p.symbol:
        return p.symbol
    isin = (p.isin or "").strip().upper()
    return isin if is_isin(isin) else None


def _position_label(p, institutions: dict[int, str]) -> str:
    """A position as the reader would find it on the page: by its ticker, or,
    with none, by the account it sits in."""
    if p.symbol:
        return p.symbol
    where = institutions.get(p.institution_id) if p.institution_id is not None else None
    return f"the {where} holding with no ticker" if where else f"{p.asset_name}, with no ticker"


def _held_more_than_once(fund: str, where: list[str]) -> str:
    """The one line for a fund under several positions: how many, named each
    way the reader would find them, and the two things it could be. The count
    is spelled out and the question follows it, so three positions are never
    asked about as "two places"."""
    n = len(where)
    count = {2: "two", 3: "three", 4: "four"}.get(n, str(n))
    times = {2: "twice", 3: "three times", 4: "four times"}.get(n, f"{n} times")
    names = ", ".join(where[:-1]) + " and " + where[-1]
    return (
        f"{fund} is held as {count} positions: {names}. "
        f"The same fund in {count} places, or one purchase entered {times}?"
    )


def compute_portfolio_composition(db: Session, refresh: bool = False) -> dict:
    """Aggregate the look-through over the whole investment portfolio.

    Position weights use book values (market pricing is a separate concern and
    this must work offline). For every symboled position the composition is
    fetched/cached; positions no source can decompose (single stocks, crypto,
    value-only lumps) stay whole in an 'undecomposed' bucket so the coverage
    is always honest. Aggregates: portfolio-level country and sector weights
    (position weight x allocation), and top-holding overlap across funds."""
    # Its own converter, so the payload can say what the values are in — the
    # base they were converted to, not a second reading of it.
    conv = fx.Converter(db)
    held = [
        p
        for p in positions.project(db, conv)
        if ((p.current_value or 0) > 0 or (p.quantity or 0) > 0) and not p.closed_on
    ]
    # Weighted by what each position is worth NOW, not by what it cost. A fund
    # that tripled carries three times the exposure it was bought with, and
    # weighting by cost would report a third of the real risk.
    total_value = sum(p.current_value for p in held) or 1.0

    rows: list[dict] = []
    countries: dict[str, float] = {}
    sectors: dict[str, float] = {}
    currencies: dict[str, float] = {}
    matrix: dict[tuple[str, str], float] = {}
    # holding name -> {"pct": portfolio %, "funds": [fund symbols], "fund_ids": {…}}
    overlap: dict[str, dict] = {}
    # One fund, by its resolved ISIN -> how each position holding it is found
    # on the page. Two entries under one ISIN is said, never merged: the same
    # fund in two accounts and one purchase entered twice look identical here,
    # and only the reader knows which it is.
    held_as: dict[str, list[str]] = {}
    fund_names: dict[str, str] = {}
    institutions = {i.id: i.name for i in crud.get_institutions(db)}
    # source -> the symbols whose holdings came from it. The overlap adds all
    # of them into one dict, and they are not the same kind of list.
    holdings_from: dict[str, list[str]] = {}
    decomposed_weight = 0.0

    for p in held:
        weight = p.current_value / total_value
        row = {
            "symbol": p.symbol,
            "asset_name": p.asset_name,
            "asset_class": p.asset_class,
            "weight_pct": round(weight * 100, 2),
            "resolved_name": None,
            "isin": None,
            "source": None,
            "fetched_at": None,
            "holdings_count": None,
            "decomposed": False,
            "error": None,
        }
        comp = None
        # Not `key`: the overlap loop below names each company `key`, and a
        # first draft of this that shared the name listed MODERNA as a fund.
        lookup = _lookup_key(p)
        if lookup:
            try:
                comp = get_composition(db, lookup, refresh=refresh, isin=p.isin)
            except CompositionError as exc:
                row["error"] = str(exc)
            except Exception as exc:
                # One unresolvable instrument must never take the whole page
                # down: a raw yfinance error on a single symbol used to 500 the
                # entire look-through. It becomes this row's reason instead.
                logger.warning(
                    "%s composition failed — %s: %s", p.symbol, type(exc).__name__, exc
                )
                row["error"] = f"{type(exc).__name__}: {exc}"
        else:
            row["error"] = "no ticker or ISIN"
        if comp is not None and (comp["countries"] or comp["sectors"]):
            row.update(
                resolved_name=comp["name"],
                isin=comp["isin"],
                source=comp["source"],
                fetched_at=comp["fetched_at"],
                holdings_count=comp["holdings_count"],
                decomposed=True,
            )
            decomposed_weight += weight
            # The fund's identity for counting: its ISIN, or the key it was
            # fetched by when no ISIN was ever found for it.
            fund_id = comp["isin"] or lookup
            if comp["isin"]:
                held_as.setdefault(comp["isin"], []).append(_position_label(p, institutions))
                if comp["name"]:
                    fund_names[comp["isin"]] = comp["name"]
            klass = p.asset_class or "unclassified"
            for c in comp["countries"]:
                countries[c["name"]] = countries.get(c["name"], 0.0) + weight * c["pct"]
                # Same numbers, two more useful lenses: what currency the risk
                # is really in, and how each asset class is spread over regions.
                cur = geo.currency_of(c["name"])
                currencies[cur] = currencies.get(cur, 0.0) + weight * c["pct"]
                cell = (klass, geo.region_of(c["name"]))
                matrix[cell] = matrix.get(cell, 0.0) + weight * c["pct"]
            for s in comp["sectors"]:
                key = _canonical_sector(s["name"])
                sectors[key] = sectors.get(key, 0.0) + weight * s["pct"]
            for h in comp["top_holdings"]:
                key = _company_key(h["name"])
                entry = overlap.setdefault(
                    key, {"pct": 0.0, "funds": [], "fund_ids": set(), "label": h["name"]}
                )
                entry["pct"] += weight * h["pct"]
                entry["funds"].append(lookup)
                entry["fund_ids"].add(fund_id)
                if len(h["name"]) > len(entry["label"]):
                    entry["label"] = h["name"]
            if comp["top_holdings"]:
                holdings_from.setdefault(comp["source"], []).append(lookup)
        rows.append(row)

    notes: list[str] = []
    # One fund under two positions, said first and named both ways, then left
    # to the reader: two accounts and a double entry look the same from here.
    for isin, where in sorted(held_as.items()):
        if len(where) >= 2:
            fund = f"{fund_names[isin]} ({isin})" if isin in fund_names else isin
            notes.append(_held_more_than_once(fund, where))

    # If an axis is empty while positions WERE decomposed, say why — an empty
    # chart with no explanation reads as "you own nothing there".
    if decomposed_weight > 0 and not countries:
        reasons = sorted(
            {e for p in held if _lookup_key(p) for e in _cached_errors(db, _lookup_key(p))}
        )
        notes.append(
            "No country breakdown available: only the sector source answered. "
            + (" · ".join(reasons) if reasons else "No reason was reported.")
        )

    # The overlap sums holdings lists of two different depths as if they were
    # comparable. When both kinds are in it, say so and name them: a company
    # held inside a fund covered only by its published top holdings, but ranked
    # below that cut, simply cannot appear — so the overlap is a floor, and a
    # floor that leans towards whichever funds had the more generous source.
    # Said only when it actually happens, because a caveat that is always on
    # screen stops being read.
    whole = sorted(
        s for src, syms in holdings_from.items() if src in _COMPLETE_HOLDINGS for s in syms
    )
    extract = sorted(
        s for src, syms in holdings_from.items() if src not in _COMPLETE_HOLDINGS for s in syms
    )
    if whole and extract:
        notes.append(
            f"Overlap is a floor: {', '.join(extract)} contributed only the top "
            f"holdings their source publishes, {', '.join(whole)} every position held."
        )

    def _ranked(d: dict[str, float]) -> list[dict]:
        return [
            {"name": k, "pct": round(v, 2)}
            for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)
            if v >= 0.01
        ]

    # Every top holding, weighted to the whole portfolio: the company axis was
    # already in the data (it is what `overlap` is computed from), so showing
    # only the overlapping subset threw away the more useful view.
    companies = [
        {"name": e["label"], "pct": round(e["pct"], 2)}
        for _, e in sorted(overlap.items(), key=lambda kv: kv[1]["pct"], reverse=True)
        if e["pct"] >= 0.01
    ]

    overlapped = [
        {
            "name": e["label"],
            "pct": round(e["pct"], 2),
            "funds": sorted(set(e["funds"])),
        }
        for _, e in sorted(overlap.items(), key=lambda kv: kv[1]["pct"], reverse=True)
        # Two FUNDS, not two positions: one fund held twice would otherwise
        # overlap with itself, company by company.
        if len(e["fund_ids"]) >= 2
    ]

    undecomposed_pct = round(max(0.0, 100.0 - decomposed_weight * 100), 2)
    return {
        "rows": rows,
        "undecomposed_pct": undecomposed_pct,
        "currencies": _ranked(currencies),
        "matrix": [
            {"asset_class": k, "region": r, "pct": round(v, 2)}
            for (k, r), v in sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)
            if v >= 0.01
        ],
        "countries": _ranked(countries),
        "sectors": _ranked(sectors),
        "companies": companies[:20],
        "overlap": overlapped[:20],
        # share of the portfolio the look-through actually covers
        "coverage_pct": round(decomposed_weight * 100, 2),
        # The denominator the weights are shares OF: what the portfolio is
        # WORTH. It was called total_book while already summing current values,
        # and a name that says cost over a number that means value is how a
        # reader ends up believing the wrong one.
        "total_value": round(total_value, 2),
        "base_currency": conv.base,
        "notes": notes,
    }


def _errors_in(row: models.CompositionCache) -> list[str]:
    """The refusals stored on a cache row, or nothing if the blob is unreadable."""
    try:
        return list(json.loads(row.data).get("errors") or [])
    except (ValueError, TypeError):
        return []


def _cached_errors(db: Session, symbol: str) -> list[str]:
    """Why the richer sources did not answer for this symbol, from its cache row."""
    row = crud.get_composition_cache(db, symbol)
    return _errors_in(row) if row is not None else []
