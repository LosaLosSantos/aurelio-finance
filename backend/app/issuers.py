"""Fund composition straight from the issuer — the authoritative source.

Third-party aggregators publish a *top ten*, which is both shallow and, as it
turns out, sometimes wrong: for iShares Edge MSCI World Min Volatility, justETF
lists NVIDIA in the top ten while the issuer's own file ranks it 12th and puts
Microsoft 7th. Anything built on a top-ten — overlap between funds above all —
inherits that error. The issuers publish EVERY position, so we ask them first.

What each one gives:
- **iShares**: 300-1300+ rows per fund, refreshed daily, with an ISIN, a
  country of risk, a sector and what the line is (its asset class: Equity,
  Fixed Income, Cash...) on every line. One screener call maps any
  ISIN to the product id; ISHARES_PRODUCT_IDS below stands in for it for
  the funds it lists, because the screener is the part that moves.
- **Vanguard**: 4000+ rows, month-end (so ~3 weeks behind), with an ISO
  country code, a sector and what the line is (`securityType`, asked since
  brief BF), but NO per-row ISIN. Its GraphQL introspection is disabled, but
  a fund's ISIN is there: the German site's product page lists every
  portfolio id it sells, and one `funds(portIds)` query on the same address
  answers each one's ISIN (brief BF, 2026-10-21). So a held Vanguard fund
  that the hand map below lacks is looked up there, and the map read is kept
  with its day (`_vanguard_port_id`). A fund of funds, whose file lists other
  funds rather than their holdings, is left to the next source (FundOfFunds).

These are the sites' own endpoints, not a documented API: they can change
without notice. That is exactly why they sit at the TOP of a waterfall rather
than alone — when one breaks, composition falls back to justETF instead of
failing (see app/composition.py).
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import threading

logger = logging.getLogger(__name__)

# Issuer files are kept WHOLE: capping them here would throw away the very
# thing they were fetched for — an overlap computed across every position
# rather than across two published top tens. ~4300 rows is a few hundred KB
# of cached JSON, which is nothing, and the UI caps what it displays.

# The map from ISIN to iShares' product id. Found 2026-09-25 by loading the
# German product screener page in Edge and recording the request the page
# itself makes. The address before it, product-screener-v3.1.jsn with a
# dcrPath, answers "File not found" since September 2026. Same shape as
# before: {productId: {"isin": ..., "portfolioId": ...}}, 1,305 funds that day.
ISHARES_SCREENER = (
    "https://www.ishares.com/varnish-api/blk-product-screener-server/api/v1/"
    "product-screener/product-data"
)
ISHARES_SCREENER_PARAMS = {
    "country": "de",
    "language": "de",
    "siteName": "de-ishares-v2",
    "userType": "individual",
}
ISHARES_HOLDINGS = (
    "https://www.ishares.com/varnish-api/uk-retail01-product-data/product-data/api/v2/"
    "get-product-data"
)
VANGUARD_GRAPHQL = "https://www.de.vanguard/gpx/graphql"

# By hand, the fallback for the day Vanguard's own list cannot be read (below):
# a fund listed here is fetched without it.
VANGUARD_PORT_IDS = {
    "IE00BK5BQT80": "9679",  # Vanguard FTSE All-World UCITS ETF (USD) Acc
    "IE00B3RBWM25": "9505",  # Vanguard FTSE All-World UCITS ETF (USD) Dist
}

# Vanguard's own list of its funds, read when a held Vanguard fund is not in
# the hand map: the German product page carries every portfolio id it sells in
# its embedded page state (`site-config.portIds`), and the GraphQL address
# above answers each one's ISIN. Measured in brief BF's P0 (2026-10-21, eight
# requests to Vanguard; the page and this query about 69 KB on the wire): 414
# portfolio ids on the page, all 414 answered with one ISIN each, the two
# pairs of the hand map among them. The query is the one sent then, word for
# word, though only the ISINs are read. Both are the site's own endpoints and
# can move without notice, like the holdings query; a read that fails is
# said, and the hand map stays.
VANGUARD_PRODUCTS_PAGE = "https://www.de.vanguard/professionell/anlageprodukte"
_VANGUARD_STATE = re.compile(r'<script id="serverApp-state"[^>]*>(.*?)</script>', re.S)
VANGUARD_FUNDS_QUERY = (
    "query FundsQuery($portIds: [String!]!) { funds(portIds: $portIds) { portId profile { "
    'portId fundFullName productTypeLevel1 polarisPdtTypeIndicator identifiers(altIds: ["ISIN"]) '
    "{ altId altIdCode altIdValue } } } }"
)
# Where the read is kept, in `settings`: the reader's day it was last read,
# the map, ISIN to portfolio id, every read's pairs added to it, and, when
# that day's answer could not be read, why (`unread`).
VANGUARD_KEPT = "vanguard_port_ids"
# One read at a time in this process: two look-throughs at once ask once.
_vanguard_guard = threading.Lock()

# The site's own holdings query, as brief BF's P0 sent it (2026-10-21, word for
# word, on FTSE All-World 9679, Global Aggregate Bond EUR Hedged 9443 and
# LifeStrategy 9494): beside the four fields the look-through reads, what
# each line is (`securityType`).
VANGUARD_HOLDINGS_QUERY = "\n".join((
    "query FundsHoldingsQuery($portIds: [String!], $securityTypes: [String!], $lastItemKey: String) {",
    "    funds(portIds: $portIds) {",
    "      profile {",
    "        fundFullName",
    "        fundCurrency",
    "        primarySectorEquityClassification",
    "      }",
    "    }",
    "    borHoldings(portIds: $portIds) {",
    "      holdings(limit: 1500, securityTypes: $securityTypes, lastItemKey: $lastItemKey) {",
    "        items {",
    "          issuerName",
    "          securityLongDescription",
    "          gicsSectorDescription",
    "          icbSectorDescription",
    "          icbIndustryDescription",
    "          marketValuePercentage",
    "          sedol1",
    "          quantity",
    "          ticker",
    "          securityType",
    "          finalMaturity",
    "          effectiveDate",
    "          marketValueBaseCurrency",
    "          bloombergIsoCountry",
    "          couponRate",
    "        }",
    "        totalHoldings",
    "        lastItemKey",
    "      }",
    "    }",
    "  }",
))
# The `securityType`s that are a company's shares: the site's own stock codes
# (its bundle groups them, P0) but a fund's (EQ.ETF, MF.MF) and an option's
# (EQ.RIGHT, EQ.WRT). On P0's first pages these five were read: EQ.STOCK,
# EQ.REIT, EQ.PREF, EQ.DRCPT, EQ.FSH; EQ.PSH is the site's, not seen. Every
# other code (a bond's FI.*, money market MM.*, currency CT.* and CRNY, a
# derivative DE.*) is said as it is, and is no company (`composition._a_share`).
VANGUARD_SHARES = frozenset({"EQ.STOCK", "EQ.REIT", "EQ.PREF", "EQ.DRCPT", "EQ.FSH", "EQ.PSH"})
VANGUARD_FUNDS = frozenset({"EQ.ETF", "MF.MF"})
# A file more than half of whose value is in other funds' lines is a fund of
# funds, and its lines are not its holdings: their countries are where those
# funds are listed. Measured in P0: LifeStrategy 9494, 99.5335% in EQ.ETF
# lines (its whole file, 17 lines), read as United Kingdom 64.38% and Germany
# 35.15%; FTSE All-World and Global Aggregate Bond, 0% on their first pages.
# Half is the word "mostly"; nothing measured falls between.
FUND_OF_FUNDS_ABOVE_PCT = 50.0

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

# Hand-maintained, like VANGUARD_PORT_IDS, for the day the screener moves: a
# fund listed here is fetched without it. An id goes in only after a holdings
# call for it returned the fund's own ISIN, with the date that was checked.
ISHARES_PRODUCT_IDS: dict[str, str] = {}

# The screener is one 3.7 MB download for ~1300 funds: hold it for a day.
_ISHARES_MAP: dict[str, str] | None = None
_ISHARES_MAP_AT: datetime.datetime | None = None
SCREENER_TTL_HOURS = 24


class IssuerError(Exception):
    """Raised when an issuer cannot supply a fund's holdings."""


class IssuerUnreachable(IssuerError):
    """The issuer could not be asked at all: an endpoint moved or did not
    answer. Not "this is not our fund", which is a plain IssuerError: the
    next adapter still gets its turn, and this reason is kept so the cached
    entry can say in words why the issuer's file is missing."""


class FundOfFunds(IssuerError):
    """The issuer's file is the fund's own and lists other funds, not their
    holdings (a Vanguard LifeStrategy fund): read as holdings, those funds'
    listing countries would stand for its exposure. Its reason is kept, as an
    unreachable issuer's is, and the fund falls to the next source."""


class VanguardListUnread(IssuerUnreachable):
    """Vanguard answered, and its list of funds could not be read from the
    answer: the page no longer carries it, or the query was refused or gave no
    ISIN. Kept with the day and said again that day without asking
    (`_vanguard_port_id`); a list that did not answer is not kept, and is
    asked again at the next look."""


def _plain(value):
    """The screener wraps some values as {'r': raw, 'd': display}."""
    if isinstance(value, dict):
        return value.get("r", value.get("d"))
    return value


def _ishares_product_ids() -> dict[str, str]:
    """{ISIN: productId} for every iShares UCITS fund. Network call, cached."""
    global _ISHARES_MAP, _ISHARES_MAP_AT
    import httpx

    now = datetime.datetime.now(datetime.timezone.utc)
    if (
        _ISHARES_MAP is not None
        and _ISHARES_MAP_AT is not None
        and (now - _ISHARES_MAP_AT) <= datetime.timedelta(hours=SCREENER_TTL_HOURS)
    ):
        return _ISHARES_MAP

    try:
        resp = httpx.get(
            ISHARES_SCREENER,
            params=ISHARES_SCREENER_PARAMS,
            headers={"User-Agent": _UA},
            timeout=60,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise IssuerUnreachable(
            f"iShares' product screener did not answer ({type(exc).__name__})"
        ) from exc
    if resp.status_code == 404:
        # What it answered from September 2026, while the holdings endpoint
        # kept working. Said in words, because the next person to meet it
        # should see why in one line, not a status code. The day is the
        # reader's local one, as `dated.local_day` reads a stored timestamp.
        seen = now.astimezone().date().isoformat()
        raise IssuerUnreachable(
            f"iShares moved its product screener: {ISHARES_SCREENER} answers "
            f"'File not found' (seen {seen}). Its funds fall back "
            "to the next source until the screener's new address, or the fund's "
            "product id in ISHARES_PRODUCT_IDS, is in app/issuers.py."
        )
    resp.raise_for_status()
    out: dict[str, str] = {}
    for product_id, product in resp.json().items():
        isin = _plain(product.get("isin"))
        if isinstance(isin, str) and isin:
            out[isin.upper()] = str(product_id)
    _ISHARES_MAP, _ISHARES_MAP_AT = out, now
    return out


def _aggregate(rows: list[dict], name: str | None) -> dict:
    """Turn a full holdings list into the axes the look-through needs.

    Weights are summed per country and per sector rather than taken from a
    published summary, so every axis comes from the same rows and always adds
    up to the same total."""
    countries: dict[str, float] = {}
    sectors: dict[str, float] = {}
    for r in rows:
        pct = r["pct"]
        if r["country"]:
            countries[r["country"]] = countries.get(r["country"], 0.0) + pct
        if r["sector"]:
            sectors[r["sector"]] = sectors.get(r["sector"], 0.0) + pct

    ranked = sorted(rows, key=lambda r: r["pct"], reverse=True)
    # A line's kind travels only where its file said one: absent and "not said"
    # are the same answer, and every entry cached before reads that way.
    return {
        "name": name,
        "countries": sorted(
            ({"name": k, "pct": round(v, 2)} for k, v in countries.items()),
            key=lambda x: x["pct"],
            reverse=True,
        ),
        "sectors": sorted(
            ({"name": k, "pct": round(v, 2)} for k, v in sectors.items()),
            key=lambda x: x["pct"],
            reverse=True,
        ),
        "top_holdings": [
            {
                "name": r["name"],
                "pct": round(r["pct"], 4),
                "isin": r.get("isin"),
                **({"kind": r["kind"]} if r.get("kind") else {}),
            }
            for r in ranked
        ],
        "holdings_count": len(rows),
    }


def fetch_ishares(isin: str) -> dict:
    """Every position of an iShares fund, by ISIN. Network calls; raises."""
    import httpx

    product_id = ISHARES_PRODUCT_IDS.get(isin.upper()) or _ishares_product_ids().get(isin.upper())
    if not product_id:
        raise IssuerError(f"{isin} is not an iShares product")

    resp = httpx.get(
        ISHARES_HOLDINGS,
        params={
            "appSubType": "ISHARES",
            "appType": "PRODUCT_PAGE",
            "component": "holdings",
            "locale": "en_GB",
            "portfolioId": product_id,
            "targetSite": "ishares-uk",
            "userType": "individual",
            "excludeContent": "true",
            "includeConfig": "false",
        },
        headers={"User-Agent": _UA},
        timeout=60,
        follow_redirects=True,
    )
    resp.raise_for_status()
    points = (
        resp.json()["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"][
            "dataPointsByNameMap"
        ]
    )

    def column(key: str) -> list:
        return (points.get(key) or {}).get("value") or []

    names, isins = column("issueName"), column("isin")
    pcts, countries, sectors = (
        column("holdingPercent"),
        column("countryOfRisk"),
        column("sectorName"),
    )
    # What each line is, as the file says it. Read on 2026-10-12 (brief AR) in
    # two files: an equity fund's 1,249 "Equity" lines beside "Cash", "FX",
    # "Futures" and "Money Market" ones, and a bond fund's 19,977 "Fixed
    # Income". A bond fund lists its issuers' notes under the issuers' own
    # names, so without this a company's debt met its shares held by an equity
    # fund as one stock held twice (`composition._a_share`).
    kinds = column("assetClass")
    if not names:
        raise IssuerError(f"iShares returned no holdings for {isin}")

    rows = []
    for i, name in enumerate(names):
        try:
            pct = float(pcts[i])
        except (IndexError, TypeError, ValueError):
            continue
        country = countries[i] if i < len(countries) else None
        kind = str(kinds[i]).strip() if i < len(kinds) and kinds[i] else ""
        rows.append(
            {
                "name": str(name).title(),
                "isin": (isins[i] if i < len(isins) else None) or None,
                "pct": pct,
                # "-" is how the file marks cash and derivatives: real
                # information, so it becomes Other rather than vanishing.
                "country": None if country in (None, "", "-") else str(country),
                "sector": (sectors[i] if i < len(sectors) else None) or None,
                "kind": kind or None,
            }
        )
    return _aggregate(rows, None)


def _named_vanguard(isin: str) -> bool:
    """Whether the stored fund catalogue names `isin` as one of Vanguard's
    funds. Vanguard's list is read only for those, so a reader who holds no
    Vanguard fund never asks Vanguard anything; a fund the catalogue does not
    list is not asked about either, and the hand map is its way in."""
    from app import models
    from app.database import SessionLocal

    with SessionLocal() as db:
        fund = db.get(models.Instrument, isin)
        return fund is not None and fund.name.strip().lower().startswith("vanguard")


def _vanguard_pairs(payload) -> dict[str, str]:
    """{ISIN: portfolio id} from the funds query's answer. An entry not of
    the shape measured (a null fund or identifier, a `data` that is not an
    object) is skipped rather than raised; an answer that carries errors
    beside its funds keeps the pairs it holds."""
    data = payload.get("data") if isinstance(payload, dict) else None
    funds = data.get("funds") if isinstance(data, dict) else None
    ports: dict[str, str] = {}
    for fund in funds if isinstance(funds, list) else []:
        if not isinstance(fund, dict) or not fund.get("portId"):
            continue
        profile = fund.get("profile")
        identifiers = profile.get("identifiers") if isinstance(profile, dict) else None
        for ident in identifiers if isinstance(identifiers, list) else []:
            if isinstance(ident, dict) and ident.get("altIdCode") == "ISIN" and ident.get("altIdValue"):
                ports[str(ident["altIdValue"]).strip().upper()] = str(fund["portId"])
    return ports


def _read_vanguards_list() -> dict[str, str]:
    """{ISIN: portfolio id} for every fund Vanguard's German site lists: its
    product page, then one query for the ISINs. Two network calls. Raises,
    in words, VanguardListUnread when Vanguard answered and the list could
    not be read from its answer, and IssuerUnreachable when it did not answer
    (a failed connection or a 5xx)."""
    import httpx

    seen = datetime.datetime.now(datetime.timezone.utc).astimezone().date().isoformat()
    try:
        page = httpx.get(
            VANGUARD_PRODUCTS_PAGE, headers={"User-Agent": _UA}, timeout=60, follow_redirects=True
        )
    except httpx.HTTPError as exc:
        raise IssuerUnreachable(
            f"Vanguard's product page did not answer ({type(exc).__name__})"
        ) from exc
    if page.status_code != 200:
        said = f"Vanguard's product page answered {page.status_code} (seen {seen})"
        if page.status_code >= 500:
            raise IssuerUnreachable(said)
        raise VanguardListUnread(said)
    found = _VANGUARD_STATE.search(page.text)
    try:
        state = json.loads(found.group(1)) if found else {}
        listed = state["_angular_initial_state"][":items"]["root"][":items"]["site-config"]["portIds"]
        port_ids = [p.strip() for p in str(listed).split(",") if p.strip()]
    except (ValueError, KeyError, TypeError):
        port_ids = []
    if not port_ids:
        raise VanguardListUnread(
            f"Vanguard's product page no longer lists its funds where the app reads them "
            f"({VANGUARD_PRODUCTS_PAGE}, seen {seen}). A fund missing from VANGUARD_PORT_IDS in "
            "app/issuers.py falls back to the next source."
        )
    try:
        resp = httpx.post(
            VANGUARD_GRAPHQL,
            headers={"Content-Type": "application/json", "X-Consumer-ID": "de7", "User-Agent": _UA},
            json={
                "operationName": "FundsQuery",
                "variables": {"portIds": port_ids},
                "query": VANGUARD_FUNDS_QUERY,
            },
            timeout=60,
        )
    except httpx.HTTPError as exc:
        raise IssuerUnreachable(
            f"Vanguard's list of funds did not answer ({type(exc).__name__})"
        ) from exc
    if resp.status_code >= 500:
        raise IssuerUnreachable(f"Vanguard's list of funds answered {resp.status_code} (seen {seen})")
    try:
        payload = resp.json() if resp.status_code == 200 else None
    except ValueError:
        payload = None
    ports = _vanguard_pairs(payload)
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if ports:
        if errors:
            logger.warning(
                "Vanguard's list of funds answered %d ISINs and errors: %s", len(ports), str(errors)[:300]
            )
        return ports
    if not isinstance(payload, dict) or errors:
        said = str(errors)[:120] if errors else resp.status_code
        raise VanguardListUnread(f"Vanguard refused the query for its list of funds ({said})")
    raise VanguardListUnread(f"Vanguard's list of funds answered no ISIN (seen {seen})")


def _kept_vanguards() -> tuple[str | None, dict[str, str], str | None]:
    """The read kept in `settings`: its day, its map, and why that day's read
    failed when Vanguard answered and its list could not be read; or
    (None, {}, None)."""
    from app import models
    from app.database import SessionLocal

    with SessionLocal() as db:
        row = db.get(models.Setting, VANGUARD_KEPT)
    try:
        kept = json.loads(row.value) if row is not None and row.value else {}
        ports = {str(k): str(v) for k, v in dict(kept.get("ports") or {}).items()}
        return kept.get("day"), ports, kept.get("unread")
    except (ValueError, TypeError, AttributeError):
        return None, {}, None


def _keep_vanguards(day: str, ports: dict[str, str], unread: str | None = None) -> None:
    """Keep the read in `settings`. A write that fails (the database still
    busy past its wait) is logged, not raised: what was just read serves the
    look-through that asked, and the list is read again at the next."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.exc import SQLAlchemyError

    from app import models
    from app.database import SessionLocal, sole_writer

    kept = {"day": day, "ports": ports, **({"unread": unread} if unread else {})}
    value = json.dumps(kept, separators=(",", ":"))
    try:
        with SessionLocal() as db:
            with sole_writer(db):
                row = sqlite_insert(models.Setting).values(key=VANGUARD_KEPT, value=value)
                db.execute(row.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
    except SQLAlchemyError as exc:
        logger.warning("Vanguard's list was read and could not be kept: %s", exc)


def _vanguard_port_id(isin: str) -> str | None:
    """The portfolio id of a Vanguard fund: the hand map's, else the one kept
    from Vanguard's own list. That list is read only for a fund the stored
    catalogue names as Vanguard's and the kept map lacks, and at most once a
    day: a read Vanguard answered and whose list could not be read
    (VanguardListUnread) is kept with its day and its reason, said again that
    day without asking; one that did not answer is kept nowhere, and is asked
    again at the next look, as an outage is elsewhere in the app. Each read
    adds to the map, so a fund once found keeps its id when a later list no
    longer names it, and nothing is asked again for it. None for a fund that
    is not Vanguard's, or that Vanguard's list did not hold when read today.
    Raises IssuerUnreachable, said in words, when the list could not be
    read."""
    from app import dated

    if isin in VANGUARD_PORT_IDS:
        return VANGUARD_PORT_IDS[isin]
    _, ports, _ = _kept_vanguards()
    if isin in ports:
        return ports[isin]
    if not _named_vanguard(isin):
        return None
    today = dated.today()
    with _vanguard_guard:
        day, ports, unread = _kept_vanguards()
        if isin in ports:
            return ports[isin]
        if day == today:
            if unread:
                raise VanguardListUnread(unread)
            return None
        try:
            read = _read_vanguards_list()
        except VanguardListUnread as exc:
            _keep_vanguards(today, ports, str(exc))
            raise
        ports = {**ports, **read}
        _keep_vanguards(today, ports)
        return ports.get(isin)


def _vanguard_kind(security_type) -> str | None:
    """What a Vanguard line is, in the look-through's words: "Equity" for a
    company's shares (VANGUARD_SHARES), the file's own code for anything else,
    None where the file says nothing."""
    code = str(security_type or "").strip()
    if not code:
        return None
    return "Equity" if code in VANGUARD_SHARES else code


def fetch_vanguard(isin: str) -> dict:
    """Every position of a Vanguard UCITS fund, by ISIN (month-end data), each
    line with what it is. Network calls; raises, FundOfFunds for a file more
    than half of whose value is other funds."""
    import httpx

    from app import geo

    port_id = _vanguard_port_id(isin.upper())
    if not port_id:
        raise IssuerError(f"{isin} has no known Vanguard portfolio id")

    rows: list[dict] = []
    last_key = None
    for _ in range(10):  # 1500 per page; a guard, not a real limit
        resp = httpx.post(
            VANGUARD_GRAPHQL,
            headers={
                "User-Agent": _UA,
                "Content-Type": "application/json",
                "X-Consumer-ID": "de7",
                "Accept": "application/json",
            },
            json={
                "operationName": "FundsHoldingsQuery",
                "variables": {"portIds": [port_id], "lastItemKey": last_key},
                "query": VANGUARD_HOLDINGS_QUERY,
            },
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise IssuerError(f"Vanguard GraphQL: {str(payload['errors'])[:120]}")
        holdings_node = (payload.get("data") or {}).get("borHoldings")
        if isinstance(holdings_node, list):
            holdings_node = holdings_node[0] if holdings_node else None
        block = (holdings_node or {}).get("holdings") or {}
        for item in block.get("items") or []:
            try:
                pct = float(item.get("marketValuePercentage"))
            except (TypeError, ValueError):
                continue
            kind = _vanguard_kind(item.get("securityType"))
            rows.append(
                {
                    "name": str(item.get("issuerName") or "").strip(),
                    "isin": None,  # Vanguard publishes SEDOL/ticker, not ISIN
                    "pct": pct,
                    "country": geo.country_from_iso2(item.get("bloombergIsoCountry")),
                    "sector": item.get("gicsSectorDescription") or None,
                    **({"kind": kind} if kind else {}),
                }
            )
        last_key = block.get("lastItemKey")
        if not last_key:
            break
    if not rows:
        raise IssuerError(f"Vanguard returned no holdings for {isin}")
    in_funds = sum(r["pct"] for r in rows if r.get("kind") in VANGUARD_FUNDS)
    if in_funds > FUND_OF_FUNDS_ABOVE_PCT:
        raise FundOfFunds(
            f"Vanguard's file for {isin} lists other funds ({in_funds:.2f}% of it), not "
            "their holdings: a fund of funds is read from the next source."
        )
    return _aggregate(rows, None)


def fetch(isin: str) -> dict:
    """The fund's full composition from whichever issuer publishes it.
    Raises IssuerError when no adapter covers this ISIN."""
    isin = (isin or "").strip().upper()
    if not isin:
        raise IssuerError("No ISIN")
    unanswered: list[str] = []
    for adapter in (fetch_ishares, fetch_vanguard):
        try:
            return adapter(isin)
        except IssuerUnreachable as exc:
            # Could not ask this issuer, so it may or may not be its fund:
            # the next adapter is asked anyway, and the reason is kept.
            unanswered.append(str(exc))
        except FundOfFunds as exc:
            # Its fund, and a file that is not its holdings: said too.
            unanswered.append(str(exc))
        except IssuerError:
            continue  # not this issuer's fund
    if unanswered:
        raise IssuerError("; ".join(unanswered))
    raise IssuerError(f"No issuer adapter covers {isin}")
