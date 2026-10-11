"""The analysis sees the money and the property beside the investments.

Run 1, on 2026-10-02, judged a share "at risk" on the investments alone and
asked the reader how much cash they could reach tomorrow, while much of what
they hold is cash on their accounts: no seat of the chain was given it. The
reader chose, the same day, that the analyst reads the records as the chat
reads them: the cash on each account, the income and expenses in force today
with the months the cash covers, the real assets and the debts, names
included, and the wholes every share is taken from.

The chain's asymmetry still holds and these tests lean on it: the analyst is
given records and no person (no profile, no goals), the confidant the person
and no figure. Every name and value in these fixtures is invented.
"""

from __future__ import annotations

import datetime

import pytest

from app import advisor, analytics, chain, models, tools
from app.database import SessionLocal

TODAY = datetime.date.today()
LONG_AGO = (TODAY - datetime.timedelta(days=400)).isoformat()
PAST = (TODAY - datetime.timedelta(days=60)).isoformat()
ENDED = (TODAY - datetime.timedelta(days=10)).isoformat()
SOON = (TODAY + datetime.timedelta(days=30)).isoformat()
LATER = (TODAY + datetime.timedelta(days=90)).isoformat()


def _made(response) -> int:
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _bank(client, name: str, cash: float | None = None) -> int:
    iid = _made(client.post("/api/institutions", json={"name": name}))
    if cash is not None:
        _made(client.post(f"/api/institutions/{iid}/cash-anchors",
                          json={"date": PAST, "amount": cash, "currency": "EUR"}))
    return iid


@pytest.fixture
def records(client):
    """Cash on one account and none entered on another, one fund, flows in
    force, scheduled, ended and undated, a valued house and an unvalued watch,
    a debt on the house, and something personal in the questionnaire. The
    flows are linked to no account, so the register stays at its anchor."""
    alfa = _bank(client, "Banca Alfa", cash=6000)
    _bank(client, "Banca Beta")
    sid = _made(client.post(f"/api/institutions/{alfa}/snapshots", json={"date": PAST}))
    _made(client.post(f"/api/snapshots/{sid}/holdings",
                      json={"asset_name": "Fondo Alfa", "asset_class": "fund_etf",
                            "symbol": "ALFA.MI", "quantity": 10, "unit_price": 100,
                            "currency": "EUR"}))

    def income(name, amount, start, **extra):
        return _made(client.post("/api/income-sources", json={
            "name": name, "amount": amount, "currency": "EUR", "frequency": "monthly",
            "kind": "active", "category": "salary", "start_date": start, **extra}))

    def expense(name, amount, start, nature, category, **extra):
        return _made(client.post("/api/expenses", json={
            "name": name, "amount": amount, "currency": "EUR", "frequency": "monthly",
            "nature": nature, "category": category, "start_date": start, **extra}))

    income("Stipendio", 3000, LONG_AGO)
    income("Nuovo lavoro", 4000, SOON)
    expense("Affitto", 1000, LONG_AGO, "essential", "housing")
    expense("Regalo per Marta", 200, None, "essential", "other")
    expense("Palestra", 50, LONG_AGO, "discretionary", "leisure", end_date=ENDED)
    expense("Retta scuola", 600, SOON, "essential", "education")
    expense("Auto nuova", 10000, LATER, "discretionary", "transport", frequency="one_off")

    house = _made(client.post("/api/real-assets",
                              json={"name": "Casa al mare", "category": "house", "currency": "EUR"}))
    _made(client.post(f"/api/real-assets/{house}/valuations", json={"date": PAST, "value": 300000}))
    _made(client.post("/api/real-assets",
                      json={"name": "Orologio", "category": "collectible", "currency": "EUR"}))
    loan = _made(client.post("/api/liabilities", json={
        "name": "Prestito di papà", "kind": "loan", "currency": "EUR",
        "interest_rate": 2.5, "real_asset_id": house}))
    _made(client.post(f"/api/liabilities/{loan}/balances", json={"date": PAST, "balance": 5000}))

    client.put("/api/survey", json=[{
        "question_key": "self_narrative", "topic": "In your words",
        "question": "Tell us about yourself", "answer": "I panic when markets drop."}])


def _analyst(db) -> str:
    return advisor.build_portfolio_context(db)


# --- The cash -----------------------------------------------------------------


def test_the_analyst_reads_the_cash_on_each_account_as_the_chat_does(records):
    with SessionLocal() as db:
        analyst, chat = _analyst(db), advisor.build_context(db)

    alfa = next(line for line in chat.splitlines() if line.startswith("- Banca Alfa: "))
    assert alfa in analyst.splitlines(), "the same line, from the same renderer"
    assert "- Banca Beta: no cash anchor set yet" in analyst
    assert (
        "- TOTAL cash on the accounts: 6000.00, not counting Banca Beta: no cash anchor "
        "is set there, so that cash is not known"
    ) in analyst


def test_cash_nobody_entered_is_not_cash_of_zero(client):
    _bank(client, "Banca Alfa")
    with SessionLocal() as db:
        analyst = _analyst(db)
    assert (
        "- The cash on the accounts is not known: no account has a cash anchor set, so "
        "no total that includes it (the liquid wealth, everything the person owns, the "
        "net worth), no share of one, and no number of months the cash covers can be "
        "stated."
    ) in analyst
    for stated in ("The investments are", "The cash covers", "- Everything the person owns",
                   "- Net worth"):
        assert stated not in analyst


# --- The flows ------------------------------------------------------------------


def test_only_the_flows_in_force_today_are_counted_and_the_others_are_listed_apart(records):
    with SessionLocal() as db:
        analyst = _analyst(db)

    assert "- Income: 3000.00 a month" in analyst
    # The rent and the undated 200; the gym ended ten days ago.
    assert "- Expenses: 1200.00 a month (essential 1200.00, discretionary 0.00)" in analyst
    assert "- Left each month (income minus expenses): 1800.00" in analyst
    assert "- 1 of these flows has no start date, so it is counted as in force." in analyst
    assert (
        "- Income in force today:\n"
        f"  - Stipendio [active/salary] 3000.00 EUR monthly, on no account, since {LONG_AGO}"
    ) in analyst
    assert (
        "- Expenses in force today:\n"
        f"  - Affitto [essential/housing] 1000.00 EUR monthly, on no account, since {LONG_AGO}\n"
        "  - Regalo per Marta [essential/other] 200.00 EUR monthly, on no account, no start date"
    ) in analyst
    assert "- Starting after today, so NOT counted above:" in analyst
    assert f"  - income: Nuovo lavoro [active/salary] 4000.00 EUR monthly, on no account, from {SOON}" in analyst
    assert f"  - expense: Retta scuola [essential/education] 600.00 EUR monthly, on no account, from {SOON}" in analyst
    assert (
        f"  - expense: Auto nuova [discretionary/transport] 10000.00 EUR one_off, on no account, from {LATER}"
    ) in analyst
    # Listed apart since brief AI, so the figures can be explained, and still
    # not in them; brief Z had dropped an ended flow altogether.
    assert (
        "- Ended before today, so NOT counted above:\n"
        f"  - expense: Palestra [discretionary/leisure] 50.00 EUR monthly, on no account, since {LONG_AGO}, "
        f"until {ENDED}"
    ) in analyst


def test_a_flow_reaches_the_analyst_and_the_chat_as_one_line_with_its_dates(records):
    with SessionLocal() as db:
        analyst, chat = _analyst(db), advisor.build_context(db)
    line = f"  - Affitto [essential/housing] 1000.00 EUR monthly, on no account, since {LONG_AGO}"
    assert line in chat.splitlines()
    assert line in analyst.splitlines()


def test_the_page_reads_the_figures_the_analysis_reads(records, client):
    """The Cash flow page counted every flow whatever its dates, the job that
    has not started included (7000.00 of income), until brief AI moved it onto
    the analysis's own computation."""
    flow = client.get("/api/dashboard/cashflow").json()
    assert (flow["monthly_income"], flow["monthly_expenses"], flow["monthly_net"]) == (
        3000.0, 1200.0, 1800.0,
    )


def test_no_flow_in_force_is_said_as_none_not_as_zero(client):
    """A reader who has recorded no income has not said they earn nothing, and
    a monthly net computed against nothing reads as a loss they never stated."""
    _made(client.post("/api/income-sources", json={
        "name": "Nuovo lavoro", "amount": 4000, "currency": "EUR", "frequency": "monthly",
        "start_date": SOON}))
    with SessionLocal() as db:
        analyst = _analyst(db)
    assert "- Income: none in force today" in analyst
    assert "- Expenses: none in force today" in analyst
    assert (
        "- What is left each month cannot be said: no income and no expense is in "
        "force today."
    ) in analyst
    assert f"  - income: Nuovo lavoro [n/a/n/a] 4000.00 EUR monthly, on no account, from {SOON}" in analyst


# --- Liquidity ------------------------------------------------------------------


def test_the_months_the_cash_covers_are_computed_by_the_app(records):
    with SessionLocal() as db:
        analyst = _analyst(db)
    assert (
        "- The cash covers 5.0 months of the essential expenses in force today "
        "(1200.00 a month). A real asset is never cash and is not counted in it."
    ) in analyst


def test_a_real_asset_never_counts_as_cash(records, client):
    """Liquidity stays liquid: adding a real asset moves what the person owns
    and nothing about what they can spend."""

    def liquidity(text: str) -> list[str]:
        return [line for line in text.splitlines()
                if line.startswith(("- The cash covers", "- Left each month", "- TOTAL cash"))]

    with SessionLocal() as db:
        before = _analyst(db)
    boat = _made(client.post("/api/real-assets",
                             json={"name": "Barca", "category": "vehicle", "currency": "EUR"}))
    _made(client.post(f"/api/real-assets/{boat}/valuations", json={"date": PAST, "value": 50000}))
    with SessionLocal() as db:
        after = _analyst(db)

    assert len(liquidity(before)) == 3
    assert liquidity(after) == liquidity(before)
    assert "- TOTAL real assets: 350000.00" in after


def test_no_essential_expense_in_force_is_said_not_divided_by(client):
    _bank(client, "Banca Alfa", cash=6000)
    _made(client.post("/api/expenses", json={
        "name": "Retta", "amount": 600, "currency": "EUR", "frequency": "monthly",
        "nature": "essential", "start_date": SOON}))
    with SessionLocal() as db:
        analyst = _analyst(db)
    assert (
        "- No essential expense is in force today, so how many months the cash covers "
        "cannot be said."
    ) in analyst


# --- The real assets and the debts ------------------------------------------------


def test_the_real_assets_reach_the_analyst_as_the_chat_reads_them(records):
    with SessionLocal() as db:
        analyst, chat = _analyst(db), advisor.build_context(db)

    for line in (f"- Casa al mare [house]: 300000.00 EUR ({PAST})", "- Orologio [collectible]: no valuation"):
        assert line in chat.splitlines() and line in analyst.splitlines()
    assert (
        "- Each value above is the person's own estimate, typed on the date beside it, "
        f"not a market price. Today is {TODAY.isoformat()}."
    ) in analyst
    assert (
        "- TOTAL real assets: 300000.00, not counting Orologio: no valuation is entered "
        "there, so that value is not known"
    ) in analyst


def test_the_debts_reach_the_analyst_as_the_chat_reads_them(records):
    with SessionLocal() as db:
        analyst, chat = _analyst(db), advisor.build_context(db)

    line = f"- Prestito di papà [loan]: 5000.00 EUR ({PAST}), rate 2.50%/yr, finances 'Casa al mare'"
    assert line in chat.splitlines() and line in analyst.splitlines()
    assert "- TOTAL debts: 5000.00" in analyst


def test_a_debt_with_no_balance_is_named_not_counted_as_zero(client):
    _bank(client, "Banca Alfa", cash=6000)
    _made(client.post("/api/liabilities",
                      json={"name": "Carta", "kind": "credit_card", "currency": "EUR"}))
    with SessionLocal() as db:
        analyst = _analyst(db)
    assert "- Carta [credit_card]: no balance yet" in analyst
    assert (
        "- TOTAL debts: 0.00, not counting Carta: no balance is entered there, so what "
        "is owed is not known"
    ) in analyst
    assert "- The debts: 0.00, not counting Carta: no balance is entered there" in analyst


# --- The wholes --------------------------------------------------------------------


def test_the_wholes_are_named_and_computed_by_the_app(records):
    with SessionLocal() as db:
        analyst = _analyst(db)
        summary = analytics.compute_summary(db)

    assert (summary["investments_total"], summary["cash_total"], summary["real_total"],
            summary["liabilities_total"], summary["net_worth"]) == (1000, 6000, 300000, 5000, 302000)
    for line in (
        "## The wholes every share is taken from (valued as the Dashboard values them)",
        "- The investments: 1000.00 (every position above, at its market price where one "
        "is known, else at its last observed value)",
        "- The cash on the accounts: 6000.00, not counting Banca Beta: no cash anchor is "
        "set there",
        "- The investments and the cash together, the liquid wealth (the Dashboard calls "
        "it Financial): 7000.00. The investments are 14.3% of it, the cash 85.7%.",
        "- The real assets: 300000.00, each at its latest valuation, the person's own "
        "estimate, not counting Orologio: no valuation is entered there",
        "- Everything the person owns, the liquid wealth and the real assets together: "
        "307000.00. The investments are 0.3% of it, the cash 2.0%, the real assets 97.7%.",
        "- The debts: 5000.00",
        "- Net worth, everything the person owns minus the debts: 302000.00",
    ):
        assert line in analyst.splitlines(), line


def test_nothing_recorded_is_said_as_none_not_as_zero(client):
    _bank(client, "Banca Alfa", cash=6000)
    with SessionLocal() as db:
        analyst = _analyst(db)
    for line in (
        "- The real assets: none recorded",
        "- The debts: none recorded",
        "- Everything the person owns: 6000.00, the liquid wealth alone, since no real "
        "asset is recorded.",
    ):
        assert line in analyst.splitlines(), line


def test_an_amount_the_app_cannot_convert_is_named_and_not_sized(client):
    """Added as written, as on the Dashboard. The amount is not given: it
    bounds no error in either direction (`fx.Converter.unconverted_amounts`)."""
    _bank(client, "Banca Alfa", cash=6000)
    land = _made(client.post("/api/real-assets",
                             json={"name": "Terreno", "category": "land", "currency": "TWD"}))
    _made(client.post(f"/api/real-assets/{land}/valuations", json={"date": PAST, "value": 1000}))
    with SessionLocal() as db:
        analyst = _analyst(db)
    assert (
        "- Amounts in TWD cannot be converted to EUR and are added as written, so the "
        "totals that hold them are not exact."
    ) in analyst.splitlines()


def test_the_investments_whole_is_the_positions_own_total(client):
    """Two functions value the positions, the Dashboard's and the one the
    positions above are written from. With a price in the cache they must say
    the same number, or the analyst reads two investments."""
    iid = _bank(client, "Banca Alfa")
    sid = _made(client.post(f"/api/institutions/{iid}/snapshots", json={"date": PAST}))
    _made(client.post(f"/api/snapshots/{sid}/holdings",
                      json={"asset_name": "Fondo Alfa", "asset_class": "fund_etf",
                            "symbol": "ALFA.MI", "quantity": 10, "unit_price": 100,
                            "currency": "EUR"}))
    with SessionLocal() as db:
        db.merge(models.PriceCache(symbol="ALFA.MI", price=120.0, currency="EUR", as_of=PAST))
        db.commit()
        analyst = _analyst(db)
    assert "- TOTAL current value: 1200.00" in analyst
    assert "- The investments: 1200.00 (" in analyst


def test_every_share_the_app_writes_names_its_whole(client, monkeypatch):
    """The look-through's weights are computed over the positions only
    (`composition.compute_portfolio_composition`, `total_value`). Beside the
    cash and the real assets, "% of whole portfolio" would read as a share of
    all of it, which is the mistake run 1 made. One fund looked through and one
    share that cannot be, so every kind of weight is written."""
    from app import composition

    iid = _bank(client, "Banca Alfa")
    sid = _made(client.post(f"/api/institutions/{iid}/snapshots", json={"date": PAST}))
    for name, symbol, cls in (("Fondo Alfa", "ALFA.MI", "fund_etf"), ("Acme", "ACME", "equity")):
        _made(client.post(f"/api/snapshots/{sid}/holdings",
                          json={"asset_name": name, "asset_class": cls, "symbol": symbol,
                                "quantity": 10, "unit_price": 100, "currency": "EUR"}))
    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda s: None)
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {"ALFA": "IE0000000001"})
    monkeypatch.setattr(
        composition, "_fetch_issuer", lambda i: (_ for _ in ()).throw(RuntimeError("no adapter"))
    )
    monkeypatch.setattr(composition, "_fetch_justetf", lambda isin: {
        "name": "Fondo Alfa",
        "countries": [{"name": "United States", "pct": 60.0}],
        "sectors": [{"name": "Technology", "pct": 30.0}],
        "top_holdings": [], "holdings_count": 1500,
    })
    with SessionLocal() as db:
        analyst = _analyst(db)

    assert "- Coverage: 50.0% of the investments decomposed;" in analyst
    assert "### Countries (% of the investments)\n- United States: 30.00%" in analyst
    assert "### Sectors (% of the investments)\n- Information Technology: 15.00%" in analyst
    assert "- Acme (ACME): 50.00% of the investments" in analyst
    assert "whole portfolio" not in analyst and "% of portfolio" not in analyst


# --- The prompts ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [advisor.PORTFOLIO_SYSTEM_PROMPT, chain.REVISION_SYSTEM_PROMPT, chain.SYNTHESIS_SYSTEM_PROMPT],
    ids=["analyst", "revision", "synthesis"],
)
def test_every_role_that_writes_figures_is_told_the_three_wholes(prompt):
    assert "names its whole" in prompt
    assert "the investments" in prompt and "liquid wealth" in prompt and "everything" in prompt


def test_the_analyst_is_told_what_it_reads_and_what_the_real_assets_are_for():
    prompt = advisor.PORTFOLIO_SYSTEM_PROMPT
    assert "ONLY the user's investment data" not in prompt
    assert "not in it at all" not in prompt
    assert "cash on each account" in prompt and "real assets" in prompt
    assert "the allocation of everything they own" in prompt
    assert "a real asset is never cash" in prompt
    assert "say how old it is" in prompt
    assert "NO personal context" in prompt


def test_the_synthesis_counts_the_real_assets_in_what_is_owned_and_not_in_what_is_spent():
    prompt = chain.SYNTHESIS_SYSTEM_PROMPT
    assert "not in the analysis" not in prompt
    assert "never in what they can spend" in prompt


# --- Who reads what -----------------------------------------------------------------


def _fake_chain(monkeypatch, verdicts):
    seen: list[dict] = []
    said = list(verdicts)

    def fake(system_prompt, user_content, model=None):
        seen.append({"system": system_prompt, "user": user_content})
        text = f"output-{len(seen)}"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += f"\n\nVERDICT: {said.pop(0) if len(said) > 1 else said[0]}"
        return {"analysis": text, "model": "m", "cost": 0.001}

    monkeypatch.setattr(advisor, "call_llm", fake)
    return seen


def _drain(db):
    walk = chain.run_chain(db)
    while True:
        try:
            next(walk)
        except StopIteration as done:
            return done.value


def test_the_revision_reads_the_records_again_and_the_confidant_never_does(records, monkeypatch):
    seen = _fake_chain(monkeypatch, ["CONTESTED", "FITS"])
    with SessionLocal() as db:
        _drain(db)

    revision = next(c for c in seen if c["system"] == chain.REVISION_SYSTEM_PROMPT)
    assert "- TOTAL cash on the accounts: 6000.00" in revision["user"]
    assert "- Casa al mare [house]" in revision["user"]
    assert revision["user"].index("# The figures you analysed") < revision["user"].index("# Your analysis")
    for confidant in (c for c in seen if c["system"] == chain.CONFIDANT_SYSTEM_PROMPT):
        for record in ("6000", "1200", "Casa al mare", "Stipendio", "Prestito"):
            assert record not in confidant["user"], f"{record!r} reached the confidant"
        assert "I panic" in confidant["user"]
    assert "I panic" not in seen[0]["user"], "the analyst is blind to the person"


def test_the_chats_look_through_names_its_whole_too():
    reading = " ".join(tools._READING)
    assert "WHOLE portfolio" not in reading
    assert "a share of the investments" in reading
    assert "investments" in tools.REGISTRY["get_look_through"].description
    assert "whole portfolio" not in tools.REGISTRY["get_look_through"].description
