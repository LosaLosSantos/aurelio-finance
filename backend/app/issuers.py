"""Fund composition straight from the issuer — the authoritative source.

Third-party aggregators publish a *top ten*, which is both shallow and, as it
turns out, sometimes wrong: for iShares Edge MSCI World Min Volatility, justETF
lists NVIDIA in the top ten while the issuer's own file ranks it 12th and puts
Microsoft 7th. Anything built on a top-ten — overlap between funds above all —
inherits that error. The issuers publish EVERY position, so we ask them first.

What each one gives:
- **iShares**: 300-1300+ rows per fund, refreshed daily, with an ISIN, a
  country of risk and a sector on every line. One screener call maps any
  ISIN to the product id; ISHARES_PRODUCT_IDS below stands in for it for
  the funds it lists, because the screener is the part that moves.
- **Vanguard**: 4000+ rows, month-end (so ~3 weeks behind), with an ISO
  country code and a sector, but NO per-row ISIN. Its GraphQL schema exposes
  no ISIN field and introspection is disabled, so ISIN -> portfolio id cannot
  be discovered programmatically; the map below is seeded by hand and grows as
  funds are needed.

These are the sites' own endpoints, not a documented API: they can change
without notice. That is exactly why they sit at the TOP of a waterfall rather
than alone — when one breaks, composition falls back to justETF instead of
failing (see app/composition.py).
"""

from __future__ import annotations

import datetime
import logging

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

# Hand-maintained because Vanguard's schema exposes no ISIN. Add a fund here
# when you own it; unmapped Vanguard funds simply fall through the waterfall.
VANGUARD_PORT_IDS = {
    "IE00BK5BQT80": "9679",  # Vanguard FTSE All-World UCITS ETF (USD) Acc
    "IE00B3RBWM25": "9505",  # Vanguard FTSE All-World UCITS ETF (USD) Dist
}

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
            {"name": r["name"], "pct": round(r["pct"], 4), "isin": r.get("isin")}
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
    if not names:
        raise IssuerError(f"iShares returned no holdings for {isin}")

    rows = []
    for i, name in enumerate(names):
        try:
            pct = float(pcts[i])
        except (IndexError, TypeError, ValueError):
            continue
        country = countries[i] if i < len(countries) else None
        rows.append(
            {
                "name": str(name).title(),
                "isin": (isins[i] if i < len(isins) else None) or None,
                "pct": pct,
                # "-" is how the file marks cash and derivatives: real
                # information, so it becomes Other rather than vanishing.
                "country": None if country in (None, "", "-") else str(country),
                "sector": (sectors[i] if i < len(sectors) else None) or None,
            }
        )
    return _aggregate(rows, None)


def fetch_vanguard(isin: str) -> dict:
    """Every position of a Vanguard UCITS fund, by ISIN (month-end data).
    Network calls; raises."""
    import httpx

    from app import geo

    port_id = VANGUARD_PORT_IDS.get(isin.upper())
    if not port_id:
        raise IssuerError(f"{isin} has no known Vanguard portfolio id")

    query = (
        "query FundsHoldingsQuery($portIds:[String!],$lastItemKey:String){"
        "borHoldings(portIds:$portIds){holdings(limit:1500,lastItemKey:$lastItemKey){"
        "items{issuerName gicsSectorDescription marketValuePercentage "
        "bloombergIsoCountry} totalHoldings lastItemKey}}}"
    )
    rows: list[dict] = []
    last_key = None
    for _ in range(10):  # 1500 per page; a guard, not a real limit
        resp = httpx.post(
            VANGUARD_GRAPHQL,
            headers={
                "Content-Type": "application/json",
                "X-Consumer-ID": "de7",
                "User-Agent": _UA,
            },
            json={
                "operationName": "FundsHoldingsQuery",
                "variables": {"portIds": [port_id], "lastItemKey": last_key},
                "query": query,
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
            rows.append(
                {
                    "name": str(item.get("issuerName") or "").strip(),
                    "isin": None,  # Vanguard publishes SEDOL/ticker, not ISIN
                    "pct": pct,
                    "country": geo.country_from_iso2(item.get("bloombergIsoCountry")),
                    "sector": item.get("gicsSectorDescription") or None,
                }
            )
        last_key = block.get("lastItemKey")
        if not last_key:
            break
    if not rows:
        raise IssuerError(f"Vanguard returned no holdings for {isin}")
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
        except IssuerError:
            continue  # not this issuer's fund
    if unanswered:
        raise IssuerError("; ".join(unanswered))
    raise IssuerError(f"No issuer adapter covers {isin}")
