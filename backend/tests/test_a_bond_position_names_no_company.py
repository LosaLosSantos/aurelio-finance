"""A position recorded as Bonds names no company, and one name is one move.

Brief BF (2026-10-22), the reader's D3 (B) and (e). Only iShares' file says
what each of a fund's lines is; every other source (justETF's top ten,
Trackinsight's, Yahoo's, Vanguard's file) says nothing, and such a line
counted as a company's shares. Measured in the brief's P0 on two invented
government bond funds read without kinds: "Italy (Republic Of) Regs" stood
among the companies at 7.5% and in the overlap, which the analyst read as the
same stock held twice. A line of no kind now takes its position's own class:
in a position recorded as Bonds it is the fund's debt. A kind the source says
still decides first, and a position recorded otherwise reads as it always did,
which the axis's descriptions say.

And a weighing matched a company across its two sides by its label, the
longest spelling each side's sources wrote, so a purchase whose source wrote a
name longer made one name two moves, 8 to 0 and 0 to 7, beside "8 to 7" in
the same answer. The companies are matched by `_company_key` now, as the
overlap matches them.

Every name, ISIN and figure here is invented."""

from __future__ import annotations

import datetime

from app import advisor, composition
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()
GOVT_A, GOVT_B, WORLD, EXTRA = "IE00ZZGOVA01", "IE00ZZGOVB02", "IE00ZZWRLD03", "IE00ZZXTRA04"


def _line(name, pct, kind=None):
    return {"name": name, "pct": pct, "isin": None, **({"kind": kind} if kind else {})}


# Two government bond funds as a top ten without kinds gives them.
GOVT_A_LINES = {
    "countries": [{"name": "Italy", "pct": 60.0}, {"name": "France", "pct": 40.0}],
    "sectors": [{"name": "Government", "pct": 100.0}],
    "top_holdings": [_line("Italy (Republic Of) Regs", 8.0), _line("France (Republic Of)", 5.0)],
}
GOVT_B_LINES = {
    "countries": [{"name": "Italy", "pct": 70.0}, {"name": "Germany", "pct": 30.0}],
    "sectors": [{"name": "Government", "pct": 100.0}],
    "top_holdings": [_line("Italy (Republic Of)", 7.0), _line("Bundesrepublik Deutschland", 4.0)],
}


def _held(client, *funds):
    """One account, one situation, each fund a position: (isin, symbol, value,
    the class it is recorded under)."""
    iid = client.post("/api/institutions", json={"name": "Banca Zeta"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    for isin, symbol, value, asset_class in funds:
        assert client.post(f"/api/snapshots/{sid}/holdings", json={
            "asset_name": f"Fondo {symbol}", "asset_class": asset_class, "symbol": symbol,
            "isin": isin, "quantity": 1, "unit_price": value, "currency": "EUR",
        }).status_code == 201


def _files(monkeypatch, files):
    """The answer for each ISIN in `files`, with no line's kind said; every
    other source has nothing."""

    def issuer(isin):
        if isin not in files:
            raise composition.CompositionError(f"no file for {isin}")
        lines = files[isin]
        return {"name": None, "holdings_count": len(lines["top_holdings"]), **lines}

    def nothing(_arg):
        raise composition.CompositionError("nothing here")

    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda symbol: None)
    monkeypatch.setattr(composition, "_fetch_issuer", issuer)
    for name in ("_fetch_justetf", "_fetch_trackinsight", "_fetch_yf_sectors"):
        monkeypatch.setattr(composition, name, nothing)
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {})
    monkeypatch.setattr(composition, "_fetch_trackinsight_isin", lambda ticker: None)


def _look_through():
    with SessionLocal() as db:
        return composition.compute_portfolio_composition(db)


# --- A position recorded as Bonds ---------------------------------------------------


def test_lines_of_no_kind_in_positions_recorded_as_bonds_name_no_company(client, monkeypatch):
    _held(client, (GOVT_A, "ZZGOVA.DE", 500, "bond"), (GOVT_B, "ZZGOVB.DE", 500, "bond"))
    _files(monkeypatch, {GOVT_A: GOVT_A_LINES, GOVT_B: GOVT_B_LINES})
    body = _look_through()
    assert body["companies"] == []
    assert body["overlap"] == []


def test_their_countries_and_sectors_still_count(client, monkeypatch):
    """Guard: only the companies and the overlap read the class."""
    _held(client, (GOVT_A, "ZZGOVA.DE", 500, "bond"), (GOVT_B, "ZZGOVB.DE", 500, "bond"))
    _files(monkeypatch, {GOVT_A: GOVT_A_LINES, GOVT_B: GOVT_B_LINES})
    body = _look_through()
    assert {c["name"]: c["pct"] for c in body["countries"]} == {
        "Italy": 65.0, "France": 20.0, "Germany": 15.0,
    }
    assert {s["name"]: s["pct"] for s in body["sectors"]} == {"Government": 100.0}


def test_the_analyst_reads_no_company_held_twice_for_two_bond_funds(client, monkeypatch):
    _held(client, (GOVT_A, "ZZGOVA.DE", 500, "bond"), (GOVT_B, "ZZGOVB.DE", 500, "bond"))
    _files(monkeypatch, {GOVT_A: GOVT_A_LINES, GOVT_B: GOVT_B_LINES})
    with SessionLocal() as db:
        context = advisor.build_portfolio_context(db)
    assert "Overlapping top holdings" not in context
    assert "Italy (Republic Of)" not in context


def test_the_same_funds_recorded_otherwise_read_as_they_always_did(client, monkeypatch):
    """The one case left, said in the axis's descriptions: a bond fund recorded
    under Stocks & ETF, read from a source that says nothing of its lines."""
    _held(client, (GOVT_A, "ZZGOVA.DE", 500, "fund_etf"), (GOVT_B, "ZZGOVB.DE", 500, "equity"))
    _files(monkeypatch, {GOVT_A: GOVT_A_LINES, GOVT_B: GOVT_B_LINES})
    body = _look_through()
    assert {c["name"]: c["pct"] for c in body["companies"]} == {
        "Italy (Republic Of) Regs": 7.5, "France (Republic Of)": 2.5, "Bundesrepublik Deutschland": 2.0,
    }
    (italy,) = body["overlap"]
    assert italy["name"] == "Italy (Republic Of) Regs" and italy["pct"] == 7.5


def test_a_kind_the_source_says_decides_before_the_class(client, monkeypatch):
    """A line the source calls equity is a company's shares even in a position
    recorded as Bonds; one it calls fixed income is not, in any position."""
    said = {
        "countries": [{"name": "Italy", "pct": 100.0}],
        "sectors": [{"name": "Utilities", "pct": 100.0}],
        "top_holdings": [_line("GAMMA SPA", 4.0, "Equity"), _line("Delta Spa", 3.0, "Fixed Income")],
    }
    _held(client, (GOVT_A, "ZZGOVA.DE", 500, "bond"), (WORLD, "ZZWRLD.DE", 500, "fund_etf"))
    _files(monkeypatch, {GOVT_A: said, WORLD: said})
    body = _look_through()
    assert {c["name"]: c["pct"] for c in body["companies"]} == {"GAMMA SPA": 4.0}


def test_the_rule_line_by_line():
    """The rule itself: the source's kind first, the position's class after."""
    assert composition._a_share({"name": "A"}, "bond") is False
    assert composition._a_share({"name": "A"}, "fund_etf") is True
    assert composition._a_share({"name": "A"}, "equity") is True
    assert composition._a_share({"name": "A"}, None) is True
    assert composition._a_share({"name": "A", "kind": "Equity"}, "bond") is True
    assert composition._a_share({"name": "A", "kind": "Fixed Income"}, "fund_etf") is False
    assert composition._a_share({"name": "A", "kind": "Cash"}, None) is False


# --- One name, one move ---------------------------------------------------------------


WORLD_LINES = {
    "countries": [{"name": "United States", "pct": 100.0}],
    "sectors": [{"name": "Information Technology", "pct": 100.0}],
    "top_holdings": [_line("NVIDIA Corp", 8.0), _line("Omega Inc", 4.0)],
}
EXTRA_LINES = {
    "countries": [{"name": "United States", "pct": 100.0}],
    "sectors": [{"name": "Information Technology", "pct": 100.0}],
    "top_holdings": [_line("NVIDIA Corporation", 6.0), _line("Sigma Inc", 2.0)],
}


def test_a_name_another_source_writes_longer_is_one_move(client, monkeypatch):
    """Held: a fund with NVIDIA at 8% of it, all the investments. Considered:
    as much again in a fund with NVIDIA at 6%, written longer. NVIDIA moves
    from 8% to 7%, as one name."""
    _held(client, (WORLD, "ZZWRLD.DE", 1000, "fund_etf"))
    _files(monkeypatch, {WORLD: WORLD_LINES, EXTRA: EXTRA_LINES})
    with SessionLocal() as db:
        weighed = composition.weigh_purchase(
            db, composition.Purchase(name="Fondo Extra", value=1000.0, isin=EXTRA)
        )
    nvidia = [m for m in weighed["moves"]["companies"] if "NVIDIA" in m["name"]]
    assert nvidia == [{"name": "NVIDIA Corporation", "before_pct": 8.0, "after_pct": 7.0}]
    (held,) = weighed["already_held_through_other_positions"]
    assert held["name"] == "NVIDIA Corporation" and (held["before_pct"], held["after_pct"]) == (8.0, 7.0)


def test_the_other_axes_keep_their_own_spellings():
    """Guard: countries, sectors and currencies come in one spelling each and
    are matched as they are."""
    moves = composition._moves(
        [{"name": "United States", "pct": 60.0}, {"name": "US", "pct": 0.0}],
        [{"name": "United States", "pct": 50.0}],
    )
    assert moves == [{"name": "United States", "before_pct": 60.0, "after_pct": 50.0}]


def test_a_line_no_source_named_is_one_move_too():
    """A line with an empty name (Vanguard's file has them) is labelled like
    any other: the weighing once raised KeyError on it."""
    moves = composition._moves(
        [{"name": "", "pct": 3.0}], [{"name": "", "pct": 1.0}], composition._company_key
    )
    assert moves == [{"name": "", "before_pct": 3.0, "after_pct": 1.0}]


# --- A purchase considered ----------------------------------------------------------


def test_more_of_a_fund_held_as_bonds_moves_no_company(client, monkeypatch):
    """More of a fund recorded as Bonds is read with that class, named by its
    ISIN or by its ticker: no company moves, none is said held through
    another position, and its countries keep their shares. Read with no
    class, its lines moved from nothing to its governments on the purchase's
    side alone."""
    _held(client, (GOVT_A, "ZZGOVA.DE", 1000, "bond"))
    _files(monkeypatch, {GOVT_A: GOVT_A_LINES})
    with SessionLocal() as db:
        by_isin = composition.weigh_purchase(
            db, composition.Purchase(name="Fondo ZZGOVA.DE", value=1000.0, isin=GOVT_A)
        )
        by_ticker = composition.weigh_change(
            db, purchase=composition.Purchase(name="Fondo ZZGOVA.DE", value=500.0, symbol="ZZGOVA.DE")
        )
    assert by_isin["looked_inside"] is True
    assert by_isin["moves"]["companies"] == [] and by_isin["already_held_through_other_positions"] == []
    assert by_ticker["moves"]["companies"] == []
    assert by_isin["moves"]["countries"] == [] and by_ticker["moves"]["countries"] == []


def test_a_bond_fund_not_held_is_weighed_as_before(client, monkeypatch):
    """Guard, the limit the descriptions say: a fund not held has no class on
    record, so its lines of no kind count as before, a government included."""
    _held(client, (WORLD, "ZZWRLD.DE", 1000, "fund_etf"))
    _files(monkeypatch, {WORLD: WORLD_LINES, GOVT_A: GOVT_A_LINES})
    with SessionLocal() as db:
        weighed = composition.weigh_purchase(
            db, composition.Purchase(name="Fondo Govt", value=1000.0, isin=GOVT_A)
        )
    assert {"name": "Italy (Republic Of) Regs", "before_pct": 0.0, "after_pct": 4.0} in (
        weighed["moves"]["companies"]
    )
