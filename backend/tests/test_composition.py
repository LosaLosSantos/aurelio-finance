"""ETF look-through composition: source waterfall, 15-day cache, and
portfolio-level aggregation. All network fetchers are monkeypatched."""

from __future__ import annotations

import datetime

import pytest

from app import composition

TODAY = datetime.date.today().isoformat()

CATALOGUE_MAP = {"VWCE": "IE00BK5BQT80", "SWDA": "IE00B4L5Y983"}

VWCE = {
    "isin": "IE00BK5BQT80",
    "name": "Vanguard FTSE All-World",
    "countries": [{"name": "United States", "pct": 60.0}, {"name": "Japan", "pct": 6.0}],
    "sectors": [{"name": "Technology", "pct": 30.0}, {"name": "Finance", "pct": 18.0}],
    "top_holdings": [
        {"name": "NVIDIA Corp", "pct": 4.5, "isin": "US67066G1040"},
        {"name": "Apple", "pct": 4.0, "isin": "US0378331005"},
    ],
    "holdings_count": 3768,
}

SWDA_JE = {
    "name": "iShares Core MSCI World",
    "countries": [{"name": "United States", "pct": 70.0}, {"name": "Japan", "pct": 5.0}],
    "sectors": [{"name": "Technology", "pct": 26.0}, {"name": "Finance", "pct": 16.0}],
    "top_holdings": [{"name": "NVIDIA Corp", "pct": 5.0, "isin": "US67066G1040"}],
}


def _patch_sources(
    monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue=None, issuer=None,
    equity=None, reachable=True,
):
    """Patch every network path: a dict returns it, an exception raises it,
    None raises CompositionError (that source has nothing). `catalogue` is the
    ticker -> ISIN map justETF's screener provides.

    `reachable` answers the question the cache asks before it writes a negative
    down: are the lights on? Default True, because "these sources have nothing
    on this instrument" is what these fixtures are describing — an outage is a
    different story and the test that wants one says so."""

    def make(result, label):
        def fetch(arg):
            if isinstance(result, Exception):
                raise result
            if result is None:
                raise composition.CompositionError(f"{label} empty")
            return dict(result)

        return fetch

    # The equity probe runs before the whole waterfall; unpatched it would hit
    # the network on every symbol. None means "not a plain share", which is
    # what these fixtures are (funds).
    monkeypatch.setattr(
        composition,
        "_fetch_equity_profile",
        lambda s: dict(equity) if isinstance(equity, dict) else (equity(s) if callable(equity) else None),
    )
    # The issuer sits first in the waterfall; unpatched it would hit the network.
    monkeypatch.setattr(composition, "_fetch_issuer", make(issuer, "issuer"))
    monkeypatch.setattr(composition, "_fetch_justetf", make(justetf, "justetf"))
    monkeypatch.setattr(composition, "_fetch_trackinsight", make(trackinsight, "trackinsight"))
    monkeypatch.setattr(composition, "_fetch_yf_sectors", make(yf, "yf"))
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: dict(catalogue or {}))
    monkeypatch.setattr(
        composition, "_fetch_trackinsight_isin", lambda t: (catalogue or {}).get(t)
    )
    from app import prices

    prices._reset_reachability()
    monkeypatch.setattr(prices, "_fetch_probe", lambda s: bool(reachable))


# --- Waterfall ---------------------------------------------------------------


TRACKINSIGHT = {
    "name": "Vanguard FTSE All-World",
    "countries": [{"name": "United States", "pct": 58.0}],
    "sectors": [{"name": "Technology", "pct": 28.0}],
    "top_holdings": [{"name": "NVIDIA Corp", "pct": 4.4, "isin": None}],
    "holdings_count": 3574,
}


def test_justetf_owns_the_axes_when_the_isin_resolves(client, monkeypatch):
    from app.database import SessionLocal

    _patch_sources(monkeypatch, justetf=SWDA_JE, catalogue=CATALOGUE_MAP)
    with SessionLocal() as db:
        c = composition.get_composition(db, "VWCE.MI")
    assert c["source"] == "justetf"
    assert c["countries"][0]["pct"] == 70.0
    assert c["isin"] == "IE00BK5BQT80"  # resolved from the ticker, no browser


def test_trackinsight_covers_tickers_with_no_isin(client, monkeypatch):
    """The reason Trackinsight is in the chain: it is keyed by ticker, so a
    listing whose ISIN we cannot resolve still gets a country breakdown."""
    from app.database import SessionLocal

    _patch_sources(monkeypatch, justetf=None, trackinsight=TRACKINSIGHT, catalogue={})
    with SessionLocal() as db:
        c = composition.get_composition(db, "MVOL.MI")
    assert c["source"] == "trackinsight"
    assert c["countries"][0]["name"] == "United States"
    assert c["holdings_count"] == 3574


def test_explicit_isin_on_the_holding_beats_resolution(client, monkeypatch):
    """A holding may carry its own ISIN — the ticker prices it, the ISIN
    identifies the fund — and that ISIN must win without any lookup."""
    from app.database import SessionLocal

    seen = {}

    def je(isin):
        seen["isin"] = isin
        return dict(SWDA_JE)

    _patch_sources(monkeypatch, justetf=None, catalogue={})
    monkeypatch.setattr(composition, "_fetch_justetf", je)
    with SessionLocal() as db:
        c = composition.get_composition(db, "MVOL.MI", isin="IE00B8FHGS14")
    assert seen["isin"] == "IE00B8FHGS14" and c["source"] == "justetf"


def test_yfinance_last_resort_and_total_failure(client, monkeypatch):
    from app.database import SessionLocal

    _patch_sources(
        monkeypatch,
        justetf=None,
        trackinsight=None,
        yf={"sectors": [{"name": "Technology", "pct": 30.0}], "top_holdings": []},
        catalogue={},
    )
    with SessionLocal() as db:
        c = composition.get_composition(db, "VWCE.MI")
    assert c["source"] == "yfinance" and c["countries"] == []

    _patch_sources(monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue={})
    with SessionLocal() as db:
        with pytest.raises(composition.CompositionError):
            composition.get_composition(db, "BTC-EUR", refresh=True)


def test_a_miss_on_the_isin_says_how_to_supply_it(client, monkeypatch):
    """A refusal has to carry its remedy. Trackinsight answers "no ISIN in that
    fund file" by returning None rather than raising, and the actionable line
    used to be skipped along with the raise: the user got an empty country axis
    with no reason and nothing to do. Adding the ISIN is the documented way out
    of a refusal, including a cached one, so it has to reach the row."""
    from app.database import SessionLocal

    # Nothing resolves the ticker (empty catalogue, and the Trackinsight ISIN
    # lookup reads from it too) and no source answers on its own.
    _patch_sources(monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue={})
    with SessionLocal() as db:
        with pytest.raises(composition.Undecomposable) as refusal:
            composition.get_composition(db, "MVOL.MI")

    assert any("Add the fund's ISIN" in e for e in refusal.value.errors), (
        "the one instruction that unlocks this row never reached it"
    )
    assert "Add the fund's ISIN" in str(refusal.value)


def test_isin_symbol_skips_resolution(client, monkeypatch):
    from app.database import SessionLocal

    seen = {}

    def je(isin):
        seen["isin"] = isin
        return dict(SWDA_JE)

    _patch_sources(monkeypatch, justetf=None, catalogue={})
    monkeypatch.setattr(composition, "_fetch_justetf", je)
    with SessionLocal() as db:
        c = composition.get_composition(db, "IE00B4L5Y983")
    assert seen["isin"] == "IE00B4L5Y983" and c["source"] == "justetf"


# --- Cache -------------------------------------------------------------------


def test_cache_hit_within_ttl_and_refresh_bypass(client, monkeypatch):
    from app.database import SessionLocal

    calls = {"n": 0}

    def je(isin):
        calls["n"] += 1
        return dict(VWCE)

    _patch_sources(monkeypatch, justetf=None, catalogue=CATALOGUE_MAP)
    monkeypatch.setattr(composition, "_fetch_justetf", je)
    with SessionLocal() as db:
        composition.get_composition(db, "VWCE.MI")
        composition.get_composition(db, "VWCE.MI")  # fresh -> served from cache
    assert calls["n"] == 1
    with SessionLocal() as db:
        composition.get_composition(db, "VWCE.MI", refresh=True)  # bypass TTL
    assert calls["n"] == 2


def test_stale_cache_is_refetched_and_kept_on_failure(client, monkeypatch):
    from app import crud
    from app.database import SessionLocal

    _patch_sources(monkeypatch, justetf=VWCE, catalogue=CATALOGUE_MAP)
    with SessionLocal() as db:
        composition.get_composition(db, "VWCE.MI")
        # age the entry beyond the TTL
        row = crud.get_composition_cache(db, "VWCE.MI")
        row.fetched_at = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=composition.CACHE_TTL_DAYS + 1)
        ).isoformat(timespec="seconds")
        db.commit()

    # sources down -> the stale entry still serves (stale beats nothing)
    _patch_sources(monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue={})
    with SessionLocal() as db:
        c = composition.get_composition(db, "VWCE.MI")
    assert c["source"] == "justetf"

    # sources back -> stale entry is refreshed
    fresh = dict(VWCE, holdings_count=4000)
    _patch_sources(monkeypatch, justetf=fresh, catalogue=CATALOGUE_MAP)
    with SessionLocal() as db:
        c = composition.get_composition(db, "VWCE.MI")
    assert c["holdings_count"] == 4000


def test_nothing_can_decompose_this_is_cached_like_any_other_answer(client, monkeypatch):
    """The waterfall costs three sources and two timeouts to say "no". Saying
    it again on the next page load costs the same, so it is remembered."""
    from app import crud
    from app.database import SessionLocal

    calls = {"n": 0}

    def counted(_arg):
        calls["n"] += 1
        raise composition.CompositionError("nothing here")

    # reachable=True by default: the market is up, these sources simply have
    # nothing on this one. That is the fact being cached, and it is only a fact
    # while the lights are on.
    _patch_sources(monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue={})
    monkeypatch.setattr(composition, "_fetch_trackinsight", counted)

    with SessionLocal() as db:
        with pytest.raises(composition.Undecomposable):
            composition.get_composition(db, "BTC-EUR")
        # the second ask is answered from the cache, not from the sources
        with pytest.raises(composition.Undecomposable) as second:
            composition.get_composition(db, "BTC-EUR")
    assert calls["n"] == 1

    # and it says WHY, so the row can tell the reader what to do about it
    assert second.value.errors, "the refusals were not kept"
    assert "BTC-EUR" in str(second.value)

    with SessionLocal() as db:
        row = crud.get_composition_cache(db, "BTC-EUR")
        assert row is not None and row.source == composition.UNDECOMPOSABLE
        # a negative has no countries, so it expires on the SHORT clock: this
        # answer is stable, not permanent.
        assert composition._ttl_for(row) == composition.PARTIAL_TTL_DAYS


def test_an_outage_is_not_remembered_as_a_property_of_the_instrument(client, monkeypatch):
    """The same distinction prices.py draws, one layer up: "nobody can place
    this" and "nobody answered" are different claims. Writing the second into
    the cache is how one bad afternoon becomes a fact about a fund."""
    from app import crud
    from app.database import SessionLocal

    _patch_sources(
        monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue={}, reachable=False
    )

    with SessionLocal() as db:
        with pytest.raises(composition.Undecomposable):
            composition.get_composition(db, "VWCE.MI")
        assert crud.get_composition_cache(db, "VWCE.MI") is None, (
            "an outage was remembered as if the instrument had no composition"
        )

    # the sources come back the same day and the fund decomposes normally
    _patch_sources(monkeypatch, justetf=VWCE, catalogue=CATALOGUE_MAP)
    with SessionLocal() as db:
        assert composition.get_composition(db, "VWCE.MI")["source"] == "justetf"


def test_adding_the_isin_is_not_ignored_by_a_cached_refusal(client, monkeypatch):
    """The refusal ends by telling the user to add the fund's ISIN. Doing so
    has to work the moment they do it, not the next day — an instruction the
    app then ignores is worse than no instruction."""
    from app import crud
    from app.database import SessionLocal

    # No catalogue entry, so the ticker resolves to no ISIN and nothing answers
    # — even though justETF has had the composition all along.
    _patch_sources(monkeypatch, justetf=VWCE, trackinsight=None, yf=None, catalogue={})
    with SessionLocal() as db:
        with pytest.raises(composition.Undecomposable):
            composition.get_composition(db, "VWCE.MI")
        assert crud.get_composition_cache(db, "VWCE.MI").source == composition.UNDECOMPOSABLE

    # The user does exactly what they were told. justETF has had the answer all
    # along; only the ISIN was missing.
    with SessionLocal() as db:
        c = composition.get_composition(db, "VWCE.MI", isin="IE00BK5BQT80")
    assert c["source"] == "justetf" and c["countries"]


def test_a_cached_negative_never_outranks_a_source_that_answers(client, monkeypatch):
    """The cache may only improve. A fund that gains an ISIN, an issuer file or
    a Trackinsight entry must not stay undecomposable because it once was."""
    from app import crud
    from app.database import SessionLocal

    _patch_sources(monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue={})
    with SessionLocal() as db:
        with pytest.raises(composition.Undecomposable):
            composition.get_composition(db, "VWCE.MI")
        row = crud.get_composition_cache(db, "VWCE.MI")
        assert row is not None and row.source == composition.UNDECOMPOSABLE, (
            "nothing was cached, so this test would pass without proving anything"
        )

    _patch_sources(monkeypatch, justetf=VWCE, catalogue=CATALOGUE_MAP)
    with SessionLocal() as db:
        c = composition.get_composition(db, "VWCE.MI", refresh=True)
    assert c["source"] == "justetf" and c["countries"]


# --- The refresh guard --------------------------------------------------------
#
# Shaped like a measured case: an issuer's own file lists every holding,
# where justETF publishes a top ten.

WORLD = "IE00B4L5Y983"
ISSUER_FILE = {
    "name": "iShares Core MSCI World UCITS ETF",
    "countries": [{"name": "United States", "pct": 60.0}, {"name": "Japan", "pct": 10.0}],
    "sectors": [{"name": "Industrials", "pct": 20.0}, {"name": "Financials", "pct": 15.0}],
    "top_holdings": [{"name": f"Holding {i}", "pct": 0.02, "isin": None} for i in range(1280)],
    "holdings_count": 1280,
}
TOP_TEN = {
    "name": "iShares Core MSCI World UCITS ETF",
    "countries": [{"name": "United States", "pct": 61.0}],
    "sectors": [{"name": "Industrials", "pct": 21.0}],
    "top_holdings": [{"name": f"Holding {i}", "pct": 0.3, "isin": None} for i in range(10)],
    "holdings_count": None,
}


def _days_ago(n):
    return (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=n)
    ).isoformat(timespec="seconds")


def _cache_stale(monkeypatch, **sources):
    """Cache the fund from `sources`, then age it past its TTL."""
    from app import crud
    from app.database import SessionLocal

    _patch_sources(monkeypatch, **sources)
    with SessionLocal() as db:
        composition.get_composition(db, WORLD)
        row = crud.get_composition_cache(db, WORLD)
        row.fetched_at = _days_ago(composition.CACHE_TTL_DAYS + 5)
        db.commit()
        return row.fetched_at


def _row():
    from app import crud
    from app.database import SessionLocal

    with SessionLocal() as db:
        row = crud.get_composition_cache(db, WORLD)
        import json

        return row.source, json.loads(row.data), row.fetched_at, row.refused_at


def test_a_refresh_from_the_issuers_file_to_an_extract_is_refused(client, monkeypatch):
    """The downgrade that happened on a copy of the test data: the issuer's file
    stopped answering and justETF's top ten replaced every holding."""
    from app.database import SessionLocal

    aged = _cache_stale(monkeypatch, issuer=ISSUER_FILE)
    _patch_sources(monkeypatch, issuer=None, justetf=TOP_TEN)
    with SessionLocal() as db:
        c = composition.get_composition(db, WORLD)
    assert c["source"] == "issuer" and c["holdings_count"] == 1280
    source, data, fetched_at, refused_at = _row()
    assert source == "issuer" and len(data["top_holdings"]) == 1280
    # fetched_at still says how old the data is; the refusal went elsewhere
    assert fetched_at == aged and refused_at is not None


def test_a_refused_refresh_waits_a_day_and_a_forced_one_does_not(client, monkeypatch):
    from app import crud
    from app.database import SessionLocal

    _cache_stale(monkeypatch, issuer=ISSUER_FILE)
    _patch_sources(monkeypatch, issuer=None, justetf=TOP_TEN)
    with SessionLocal() as db:
        composition.get_composition(db, WORLD)  # refused

    tried = {"n": 0}

    def issuer(isin):
        tried["n"] += 1
        return dict(ISSUER_FILE)

    _patch_sources(monkeypatch, issuer=None, justetf=TOP_TEN)
    monkeypatch.setattr(composition, "_fetch_issuer", issuer)
    with SessionLocal() as db:
        composition.get_composition(db, WORLD)
    assert tried["n"] == 0, "a refused refresh was tried again on the next load"

    with SessionLocal() as db:
        composition.get_composition(db, WORLD, refresh=True)
    assert tried["n"] == 1, "the reader's own refresh must still try"

    # a day on, the stale entry is tried again, and an accepted write clears it
    with SessionLocal() as db:
        row = crud.get_composition_cache(db, WORLD)
        row.fetched_at = _days_ago(composition.CACHE_TTL_DAYS + 5)
        row.refused_at = _days_ago(composition.PARTIAL_TTL_DAYS + 1)
        db.commit()
    with SessionLocal() as db:
        composition.get_composition(db, WORLD)
    assert tried["n"] == 2
    assert _row()[3] is None


def test_a_refresh_in_the_same_class_replaces_even_with_fewer_holdings(client, monkeypatch):
    """The same file listing a few dozen fewer holdings weeks later: an update,
    not a downgrade. A rule that counted would refuse it."""
    from app.database import SessionLocal

    aged = _cache_stale(monkeypatch, issuer=ISSUER_FILE)
    fewer = dict(ISSUER_FILE, holdings_count=1251, top_holdings=ISSUER_FILE["top_holdings"][:1251])
    _patch_sources(monkeypatch, issuer=fewer)
    with SessionLocal() as db:
        c = composition.get_composition(db, WORLD)
    assert c["holdings_count"] == 1251
    source, data, fetched_at, refused_at = _row()
    assert source == "issuer" and len(data["top_holdings"]) == 1251
    assert fetched_at != aged and refused_at is None


def test_a_refresh_from_an_extract_to_the_issuers_file_replaces(client, monkeypatch):
    from app.database import SessionLocal

    _cache_stale(monkeypatch, issuer=None, justetf=TOP_TEN)
    _patch_sources(monkeypatch, issuer=ISSUER_FILE)
    with SessionLocal() as db:
        c = composition.get_composition(db, WORLD)
    assert c["source"] == "issuer" and c["holdings_count"] == 1280


def test_a_refresh_that_loses_an_axis_is_refused(client, monkeypatch):
    """Countries, as the old guard already held, and now sectors too."""
    from app.database import SessionLocal

    for lost in ("countries", "sectors"):
        from app import crud

        with SessionLocal() as db:
            row = crud.get_composition_cache(db, WORLD)
            if row is not None:
                db.delete(row)
                db.commit()
        _cache_stale(monkeypatch, issuer=None, justetf=TOP_TEN)
        _patch_sources(monkeypatch, issuer=None, justetf=dict(TOP_TEN, **{lost: []}))
        with SessionLocal() as db:
            c = composition.get_composition(db, WORLD)
        assert c[lost], f"a refresh without {lost} replaced an entry that had them"
        assert _row()[3] is not None


# --- Portfolio aggregation ----------------------------------------------------


def _portfolio(client):
    """Two ETFs 60/40 by book value + one undecomposable stock snapshot-less."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "VWCE", "asset_class": "fund_etf", "symbol": "VWCE.MI",
              "quantity": 6, "unit_price": 100, "currency": "EUR"},  # 600
    )
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "SWDA", "asset_class": "fund_etf", "symbol": "SWDA.MI",
              "quantity": 4, "unit_price": 100, "currency": "EUR"},  # 400
    )


def test_portfolio_composition_aggregates_and_overlap(client, monkeypatch):
    _portfolio(client)

    def justetf(isin):
        if isin == "IE00BK5BQT80":
            return dict(VWCE)
        raise composition.CompositionError("justetf has nothing for SWDA")

    # A deliberately mixed portfolio: VWCE decomposes via justETF, SWDA falls
    # all the way to yfinance (sectors only, no geography).
    def yf(symbol):
        if symbol.startswith("SWDA"):
            return {
                "sectors": [{"name": "Technology", "pct": 26.0}],
                "top_holdings": [{"name": "NVIDIA Corp", "pct": 5.0, "isin": None}],
            }
        raise composition.CompositionError("no yf")

    _patch_sources(monkeypatch, justetf=None, trackinsight=None, catalogue=CATALOGUE_MAP)
    monkeypatch.setattr(composition, "_fetch_justetf", justetf)
    monkeypatch.setattr(composition, "_fetch_yf_sectors", yf)

    body = client.get("/api/dashboard/portfolio/composition").json()
    assert body["coverage_pct"] == 100.0
    # countries only from VWCE (60% weight): 0.6 * 60 = 36
    us = next(c for c in body["countries"] if c["name"] == "United States")
    assert abs(us["pct"] - 36.0) < 1e-6
    # sectors from both: tech = 0.6*30 + 0.4*26 = 28.4. Both sources said
    # "Technology"; the axis reports it under its canonical GICS name.
    tech = next(s for s in body["sectors"] if s["name"] == "Information Technology")
    assert abs(tech["pct"] - 28.4) < 1e-6
    # NVIDIA overlaps across the two funds: 0.6*4.5 + 0.4*5.0 = 4.7
    (nvidia,) = [o for o in body["overlap"] if o["name"] == "NVIDIA Corp"]
    assert abs(nvidia["pct"] - 4.7) < 1e-6
    assert sorted(nvidia["funds"]) == ["SWDA.MI", "VWCE.MI"]


def test_portfolio_composition_reports_undecomposed_honestly(client, monkeypatch):
    _portfolio(client)
    _patch_sources(monkeypatch, justetf=None, trackinsight=None, yf=None, catalogue={})

    body = client.get("/api/dashboard/portfolio/composition").json()
    assert body["coverage_pct"] == 0.0
    assert all(not r["decomposed"] and r["error"] for r in body["rows"])
    assert body["countries"] == [] and body["overlap"] == []


# --- A position with an ISIN and no ticker ------------------------------------


def _holding(client, institution, **fields):
    """One position, in an account of its own, worth 100."""
    iid = client.post("/api/institutions", json={"name": institution}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    body = {"asset_class": "fund_etf", "quantity": 1, "unit_price": 100, "currency": "EUR", **fields}
    assert client.post(f"/api/snapshots/{sid}/holdings", json=body).status_code == 201


def test_a_position_with_an_isin_and_no_ticker_is_looked_through_by_it(client, monkeypatch):
    """The ISIN is what the issuer files and justETF key on; the ticker only
    ever served to find one. A position carrying its ISIN was skipped for
    lacking the thing that exists to find what it already had."""
    from app import crud
    from app.database import SessionLocal

    _holding(client, "Broker A", asset_name="All-World", isin="IE00BK5BQT80")
    asked = []

    def justetf(isin):
        asked.append(isin)
        return dict(VWCE)

    _patch_sources(monkeypatch)
    monkeypatch.setattr(composition, "_fetch_justetf", justetf)

    body = client.get("/api/dashboard/portfolio/composition").json()
    (row,) = body["rows"]
    assert row["decomposed"] and row["source"] == "justetf" and row["isin"] == "IE00BK5BQT80"
    assert asked == ["IE00BK5BQT80"]
    assert body["coverage_pct"] == 100.0
    with SessionLocal() as db:
        assert crud.get_composition_cache(db, "IE00BK5BQT80") is not None


def test_a_position_with_neither_a_ticker_nor_an_isin_says_so(client, monkeypatch):
    _holding(client, "Broker A", asset_name="A private bond")
    _patch_sources(monkeypatch, justetf=VWCE)
    (row,) = client.get("/api/dashboard/portfolio/composition").json()["rows"]
    assert not row["decomposed"] and row["error"] == "no ticker or ISIN"


def test_a_malformed_isin_is_never_a_key(client, monkeypatch):
    """The ISIN box is free text, so eleven characters can be saved. They are
    not sent anywhere and not cached under: a key the sources cannot read would
    only cache a refusal under a typo."""
    from app import models
    from app.database import SessionLocal

    _holding(client, "Broker A", asset_name="A typo", isin="IE00BK5BQT8")
    _patch_sources(monkeypatch, justetf=VWCE)
    (row,) = client.get("/api/dashboard/portfolio/composition").json()["rows"]
    assert not row["decomposed"] and row["error"] == "no ticker or ISIN"
    with SessionLocal() as db:
        assert db.query(models.CompositionCache).count() == 0


def test_one_fund_held_twice_does_not_overlap_with_itself_and_is_named(client, monkeypatch):
    """The same fund under two positions is not two funds sharing companies.
    It is said once, naming both, and left to the reader: the same fund in two
    accounts and one purchase entered twice look identical from here."""
    _holding(client, "Broker A", asset_name="All-World", symbol="VWCE.MI")
    _holding(client, "Broker B", asset_name="All-World", isin="IE00BK5BQT80")
    _patch_sources(monkeypatch, justetf=VWCE, catalogue=CATALOGUE_MAP)

    body = client.get("/api/dashboard/portfolio/composition").json()
    assert body["overlap"] == []
    assert body["coverage_pct"] == 100.0
    (said,) = [n for n in body["notes"] if " is held as " in n]
    assert said == (
        "Vanguard FTSE All-World (IE00BK5BQT80) is held as two positions: VWCE.MI and "
        "the Broker B holding with no ticker. The same fund in two places, or one "
        "purchase entered twice?"
    )


def test_the_line_follows_the_count():
    """Three positions are not asked about as "two places"."""
    said = composition._held_more_than_once("X (IE0000000001)", ["A.MI", "B.DE", "the Broker A holding with no ticker"])
    assert said == (
        "X (IE0000000001) is held as three positions: A.MI, B.DE and the Broker A holding "
        "with no ticker. The same fund in three places, or one purchase entered three times?"
    )


def test_the_overlap_names_funds_by_their_keys_not_the_companies_in_them(client, monkeypatch):
    """A first draft of the ISIN change reused the overlap loop's variable name
    for the key, and the note that names funds read "MODERNA, MODERNA". A
    measurement on a copy of the data showed it first; three tests above would
    have too, but the draft was never run against them. This one pins it on
    the path the draft was about: a position looked up by its ISIN."""
    _holding(client, "Broker A", asset_name="All-World", symbol="VWCE.MI")
    _holding(client, "Broker B", asset_name="World", isin="IE00B4L5Y983")

    def justetf(isin):
        return dict(VWCE) if isin == "IE00BK5BQT80" else dict(SWDA_JE)

    _patch_sources(monkeypatch, catalogue=CATALOGUE_MAP)
    monkeypatch.setattr(composition, "_fetch_justetf", justetf)

    body = client.get("/api/dashboard/portfolio/composition").json()
    (nvidia,) = [o for o in body["overlap"] if o["name"] == "NVIDIA Corp"]
    assert nvidia["funds"] == ["IE00B4L5Y983", "VWCE.MI"]
    assert not [n for n in body["notes"] if " is held as " in n]


# --- Exposure lenses: currency, matrix, and the undecomposed share ------------


def test_currency_and_region_lenses_follow_the_country_weights(client, monkeypatch):
    """The same country numbers, read as currency risk and as a class x region
    grid — the two views a list of country names does not give you."""
    _portfolio(client)  # VWCE 60% of book, SWDA 40%

    both = dict(
        VWCE,
        countries=[
            {"name": "United States", "pct": 50.0},
            {"name": "Germany", "pct": 30.0},  # eurozone -> EUR
            {"name": "Japan", "pct": 20.0},
        ],
    )
    _patch_sources(
        monkeypatch,
        justetf=both,
        catalogue={"VWCE": "IE00BK5BQT80", "SWDA": "IE00B4L5Y983"},
    )

    body = client.get("/api/dashboard/portfolio/composition").json()

    # both positions decompose, so every axis covers the whole portfolio
    assert body["coverage_pct"] == 100.0 and body["undecomposed_pct"] == 0.0
    usd = next(c for c in body["currencies"] if c["name"] == "USD")
    eur = next(c for c in body["currencies"] if c["name"] == "EUR")
    assert abs(usd["pct"] - 50.0) < 1e-6  # 0.6*50 + 0.4*50
    assert abs(eur["pct"] - 30.0) < 1e-6  # Germany maps to the euro, not to DEM

    cells = {(m["asset_class"], m["region"]): m["pct"] for m in body["matrix"]}
    assert abs(cells[("fund_etf", "North America")] - 50.0) < 1e-6
    assert abs(cells[("fund_etf", "Europe")] - 30.0) < 1e-6
    assert abs(cells[("fund_etf", "Developed Asia-Pacific")] - 20.0) < 1e-6


def test_undecomposed_share_is_reported_not_normalised_away(client, monkeypatch):
    """A position nothing can look inside must show up as its own share, so a
    chart cannot quietly renormalise the rest to 100%."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "VWCE", "asset_class": "fund_etf", "symbol": "VWCE.MI",
              "quantity": 3, "unit_price": 100, "currency": "EUR"},  # 300
    )
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Bitcoin", "asset_class": "crypto", "value": 700, "currency": "EUR"},  # no symbol
    )
    _patch_sources(monkeypatch, justetf=VWCE, catalogue=CATALOGUE_MAP)

    body = client.get("/api/dashboard/portfolio/composition").json()
    assert body["coverage_pct"] == 30.0
    assert body["undecomposed_pct"] == 70.0
    # the country axis reports shares of the WHOLE portfolio, not of the 30%
    us = next(c for c in body["countries"] if c["name"] == "United States")
    assert abs(us["pct"] - 18.0) < 1e-6  # 0.3 * 60


# --- Issuer files: the authoritative source ----------------------------------


ISSUER_VWCE = {
    "name": None,
    "countries": [{"name": "United States", "pct": 62.0}],
    "sectors": [{"name": "Information Technology", "pct": 27.0}],
    # A full file, not a top ten — and the issuer shouts the name.
    "top_holdings": [
        {"name": "NVIDIA CORP", "pct": 4.44, "isin": "US67066G1040"},
        {"name": "APPLE INC", "pct": 4.23, "isin": "US0378331005"},
    ],
    "holdings_count": 4285,
}

ISSUER_MVOL = {
    "name": None,
    "countries": [{"name": "United States", "pct": 55.0}],
    "sectors": [{"name": "Health Care", "pct": 20.0}],
    "top_holdings": [
        # The same two companies, spelled the way the other issuer writes them.
        {"name": "Nvidia Corp", "pct": 1.2, "isin": "US67066G1040"},
        {"name": "Johnson & Johnson", "pct": 1.61, "isin": "US4781601046"},
    ],
    "holdings_count": 308,
}


def test_issuer_wins_over_justetf(client, monkeypatch):
    """The issuer publishes every position, so it outranks a top-ten source."""
    from app.database import SessionLocal

    _patch_sources(monkeypatch, issuer=ISSUER_VWCE, justetf=SWDA_JE, catalogue=CATALOGUE_MAP)
    with SessionLocal() as db:
        c = composition.get_composition(db, "VWCE.MI")
    assert c["source"] == "issuer"
    assert c["holdings_count"] == 4285  # not a published summary
    assert c["countries"][0]["pct"] == 62.0


def test_overlap_matches_companies_across_issuer_spellings(client, monkeypatch):
    """Two issuers write the same company differently ("NVIDIA CORP" vs
    "Nvidia Corp"). Matching raw strings drops it from the overlap — which is
    exactly how the largest shared position went missing."""
    _portfolio(client)  # VWCE 60% of book, SWDA 40%

    def issuer(isin):
        return dict(ISSUER_VWCE) if isin == "IE00BK5BQT80" else dict(ISSUER_MVOL)

    _patch_sources(monkeypatch, catalogue=CATALOGUE_MAP)
    monkeypatch.setattr(composition, "_fetch_issuer", issuer)

    body = client.get("/api/dashboard/portfolio/composition").json()
    nvidia = [o for o in body["overlap"] if "NVIDIA" in o["name"].upper()]
    assert len(nvidia) == 1, body["overlap"]
    assert sorted(nvidia[0]["funds"]) == ["SWDA.MI", "VWCE.MI"]
    # 0.6 * 4.44 + 0.4 * 1.2
    assert abs(nvidia[0]["pct"] - 3.144) < 0.01


def test_company_key_merges_legal_forms_but_not_share_classes():
    assert composition._company_key("NVIDIA CORP") == composition._company_key("Nvidia Corp")
    assert composition._company_key("Apple Inc.") == composition._company_key("APPLE INC")
    # different share classes stay different lines
    assert composition._company_key("Alphabet Inc Class A") != composition._company_key(
        "Alphabet Inc Class C"
    )


def _fund_and_share(client):
    """One fund (60%) plus one directly-held share (40%) of a company the fund
    also holds — the case the look-through used to be blind to."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "VWCE", "asset_class": "fund_etf", "symbol": "VWCE.MI",
              "quantity": 6, "unit_price": 100, "currency": "EUR"},  # 600
    )
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "NVIDIA", "asset_class": "equity", "symbol": "NVDA",
              "quantity": 4, "unit_price": 100, "currency": "EUR"},  # 400
    )


NVDA_PROFILE = {
    "name": "NVIDIA Corp",
    "country": "United States",
    "sector": "Technology",
}


def test_a_single_share_resolves_to_itself(client, monkeypatch):
    """A share is not a fund and has no holdings file — but it needs none: it
    is 100% its own country and 100% its own sector. Before this, a directly
    held stock was simply 'no data'."""
    _fund_and_share(client)
    _patch_sources(
        monkeypatch,
        justetf=VWCE,
        catalogue=CATALOGUE_MAP,
        equity=lambda s: dict(NVDA_PROFILE) if s == "NVDA" else None,
    )

    body = client.get("/api/dashboard/portfolio/composition").json()
    assert body["coverage_pct"] == 100.0
    share = next(r for r in body["rows"] if r["symbol"] == "NVDA")
    assert share["decomposed"] is True and share["source"] == "equity"
    assert share["holdings_count"] == 1


def test_direct_and_via_fund_exposure_add_up(client, monkeypatch):
    """The X-Ray: 40% held directly plus 60% x 4.5% inside the fund."""
    _fund_and_share(client)
    _patch_sources(
        monkeypatch,
        justetf=VWCE,
        catalogue=CATALOGUE_MAP,
        equity=lambda s: dict(NVDA_PROFILE) if s == "NVDA" else None,
    )

    body = client.get("/api/dashboard/portfolio/composition").json()
    nvidia = next(c for c in body["companies"] if "NVIDIA" in c["name"])
    assert abs(nvidia["pct"] - (40.0 + 0.6 * 4.5)) < 1e-6
    # and it is reported as held in both places, not just the fund
    (both,) = [o for o in body["overlap"] if "NVIDIA" in o["name"]]
    assert sorted(both["funds"]) == ["NVDA", "VWCE.MI"]


def test_a_mixed_depth_overlap_says_so(client, monkeypatch):
    """The overlap adds an issuer's whole book to somebody else's published top
    ten and presents one number. That number is a floor, and it leans towards
    the funds whose source was more generous — which the reader has to be told,
    because nothing on the chart shows it."""
    _fund_and_share(client)  # NVDA holds itself entire; VWCE comes from justETF
    _patch_sources(
        monkeypatch,
        justetf=VWCE,
        catalogue=CATALOGUE_MAP,
        equity=lambda s: dict(NVDA_PROFILE) if s == "NVDA" else None,
    )

    body = client.get("/api/dashboard/portfolio/composition").json()
    (note,) = [n for n in body["notes"] if n.startswith("Overlap is a floor")]
    # named, not "some of your funds": the names are the actionable part
    assert "NVDA" in note and "VWCE.MI" in note


def test_an_evenly_sourced_overlap_says_nothing(client, monkeypatch):
    """A caveat that is always on screen stops being read. Both funds come from
    the same kind of list here, so there is nothing to warn about."""
    _portfolio(client)  # VWCE + SWDA, both resolved through justETF
    _patch_sources(monkeypatch, justetf=VWCE, catalogue=CATALOGUE_MAP)

    body = client.get("/api/dashboard/portfolio/composition").json()
    assert [n for n in body["notes"] if n.startswith("Overlap is a floor")] == []


def test_the_two_sector_taxonomies_are_merged(client, monkeypatch):
    """Yahoo says 'Technology', the issuers say 'Information Technology'. As
    raw strings they are two sectors, which splits the biggest bar in half."""
    _fund_and_share(client)
    _patch_sources(
        monkeypatch,
        justetf={**VWCE, "sectors": [{"name": "Information Technology", "pct": 30.0}]},
        catalogue=CATALOGUE_MAP,
        equity=lambda s: dict(NVDA_PROFILE) if s == "NVDA" else None,  # says "Technology"
    )

    body = client.get("/api/dashboard/portfolio/composition").json()
    tech = [s for s in body["sectors"] if "Technology" in s["name"]]
    assert len(tech) == 1, f"the taxonomies did not merge: {tech}"
    assert abs(tech[0]["pct"] - (0.6 * 30.0 + 40.0)) < 1e-6


def test_one_broken_symbol_never_takes_the_page_down(client, monkeypatch):
    """A raw library error on a single instrument used to 500 the whole
    look-through. It must become that row's reason instead."""
    _fund_and_share(client)

    def boom(_s):
        raise RuntimeError("yfinance exploded")

    _patch_sources(monkeypatch, justetf=VWCE, catalogue=CATALOGUE_MAP, equity=boom)
    monkeypatch.setattr(composition, "_fetch_yf_sectors", boom)

    r = client.get("/api/dashboard/portfolio/composition")
    assert r.status_code == 200
    body = r.json()
    broken = next(row for row in body["rows"] if row["symbol"] == "NVDA")
    assert broken["decomposed"] is False and broken["error"]
    # the healthy fund still decomposed
    assert next(row for row in body["rows"] if row["symbol"] == "VWCE.MI")["decomposed"]


def test_one_issuer_written_two_ways_is_one_row():
    """A bond ETF lists "Italy (Republic Of)" and "Italy (Republic Of) Regs" as
    two separate holdings — one sovereign issuer offering under two
    regulations. On an axis that asks how much of the portfolio a single name
    accounts for, splitting it understates the largest exposure in the fund,
    which is exactly the failure `_company_key` exists to prevent for companies
    written differently by two issuers.

    The axis is called ISSUERS rather than companies for the same reason: a
    government is not a company, and it belongs there."""
    from app.composition import _company_key

    assert _company_key("Italy (Republic Of) Regs") == _company_key("Italy (Republic Of)")
    # And the mechanism it borrows still does its original job.
    assert _company_key("NVIDIA CORP") == _company_key("NVIDIA Corp")
    # Share classes stay apart: they are different lines and the reader should
    # see them as such.
    assert _company_key("ALPHABET INC CLASS A") != _company_key("ALPHABET INC CLASS C")
