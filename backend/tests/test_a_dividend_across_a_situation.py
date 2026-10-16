"""A dividend whose ex-date falls before a situation and whose money arrives
after it is recorded, and counted once, in the cash that follows.

Brief AZ (2026-10-16). The catch-up read only the ex-dates after the account's
latest situation, the situation being taken to account for everything before
it; but a cash balance typed on that day does not hold a dividend paid later.
Measured at `eaa89fc` on an invented household (situations of 1 June and 25
September, each with a balance of 5,000.00, the second typed before the
payment; ex-date 22 September, 3.70 credited on the 29th): nothing recorded,
the cash 5,000.00 for good. And a dividend inside an earlier stretch the
catch-up never met was never recorded at all: the dividends collected and the
tax estimate missed it.

Yahoo gives a payment date for no fund and no share outside the US (measured
the same day on 40 public tickers), so the app cannot know when the money
came. Now every stretch is read, each dividend with the units of the stretch
its ex-date falls in; a dividend whose window holds the account's latest
balance asks whether its money was already in it, and the answer dates it on
its ex-date or on the day after that balance. A row the app recorded on its
ex-date before a balance typed later is the reader's to correct with the day
it was paid, which since this brief it keeps.

Yahoo is faked where the app meets it, `prices._fetch_dividends`; the reader's
day with `dated.today`. Every name and figure is invented.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import dated, models, prices
from app.database import SessionLocal

TICKER = "XDIV.MI"
EX = "2026-09-22"
PAID = "2026-09-29"


class Yahoo:
    def __init__(self) -> None:
        self.listed = [(EX, 0.25)]
        self.asked: list[tuple[str, str]] = []

    def fetch(self, symbol: str, period: str = "max"):
        self.asked.append((symbol, period))
        events = [{"date": day, "dps": dps} for day, dps in self.listed] if symbol == TICKER else []
        return prices.DividendWindow(answered=True, dividends=events)


@pytest.fixture()
def yahoo(monkeypatch) -> Yahoo:
    fake = Yahoo()
    monkeypatch.setattr(prices, "_fetch_dividends", lambda symbol, period="max": fake.fetch(symbol, period))
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    return fake


@pytest.fixture()
def on(monkeypatch):
    def today_is(day: str) -> None:
        monkeypatch.setattr(dated, "today", lambda: day)

    today_is("2026-10-05")
    return today_is


def _account(client) -> int:
    r = client.put("/api/settings/tax",
                   json={"country": None, "capital_gains_rate": 26, "dividend_withholding_rate": 26})
    assert r.status_code == 200, r.text
    return client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]


def _situation(client, iid: int, day: str, qty: float = 20) -> None:
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": day}).json()["id"]
    r = client.post(f"/api/snapshots/{sid}/holdings",
                    json={"asset_name": "Example Dividend Share", "asset_class": "equity", "symbol": TICKER,
                          "quantity": qty, "unit_price": 50, "currency": "EUR", "distribution_policy": "dist"})
    assert r.status_code == 201, r.text


def _balance(client, iid: int, day: str, amount: float = 5000.0) -> None:
    r = client.post(f"/api/institutions/{iid}/cash-anchors", json={"date": day, "amount": amount, "currency": "EUR"})
    assert r.status_code == 201, r.text


def _catch_up(client) -> dict:
    r = client.post("/api/transactions/catch-up")
    assert r.status_code == 200, r.text
    return r.json()


def _created(result: dict) -> list[tuple]:
    return [(t["date"], t["amount"]) for t in result["created"]]


def _dividends(client) -> list[tuple]:
    return sorted(
        (t["date"], t["amount"], t.get("ex_date"), t["estimated"])
        for t in client.get("/api/transactions").json()
        if t["kind"] == "dividend"
    )


def _cash(client, iid: int) -> float:
    (cash,) = [c for c in client.get("/api/cash/positions").json() if c["institution_id"] == iid]
    return round(cash["projected"], 2)


def _collected(client) -> float:
    return round(client.get("/api/dashboard/portfolio").json()["total_dividends"], 2)


def _answer(client, iid: int, **body) -> dict:
    r = client.post("/api/transactions/dividend-answer", json={"institution_id": iid, "symbol": TICKER, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _two_situations(client) -> int:
    """The third defect's household: situations and balances of 1 June and
    25 September, the second balance typed before the payment of the 29th."""
    iid = _account(client)
    _situation(client, iid, "2026-06-01")
    _balance(client, iid, "2026-06-01")
    _situation(client, iid, "2026-09-25")
    _balance(client, iid, "2026-09-25")
    return iid


# --- The third defect --------------------------------------------------------------------------


def test_a_dividend_before_the_situation_paid_after_its_balance_is_asked_about(client, yahoo, on):
    """As measured: the ex-date of 22 September before the situation of the
    25th, whose balance the money of the 29th is not in. The app cannot know
    that from Yahoo, so it asks, and records nothing until the reader says."""
    iid = _two_situations(client)
    result = _catch_up(client)
    assert _created(result) == []
    (asked,) = result.get("questions") or [None]
    assert asked == {
        "kind": "in_balance", "institution_id": iid, "institution_name": "Broker A", "symbol": TICKER,
        "asset_name": "Example Dividend Share",
        "dividends": [{"ex_date": EX, "dps": 0.25, "currency": "EUR", "units": 20.0, "estimate": None}],
        "entries": [], "balance_date": "2026-09-25", "first_situation": None,
    }
    on("2026-10-06")
    assert len(_catch_up(client)["questions"]) == 1
    assert _dividends(client) == []


def test_its_money_came_after_the_balance_so_the_cash_that_follows_counts_it_once(client, yahoo, on):
    iid = _two_situations(client)
    _catch_up(client)
    answered = _answer(client, iid, answer="after_balance", ex_date=EX, balance_date="2026-09-25")
    assert _created(answered) == [("2026-09-26", 5.0)]
    assert answered["questions"] == []
    assert _dividends(client) == [("2026-09-26", 5.0, EX, True)]
    assert (_cash(client, iid), _collected(client)) == (5005.0, 5.0)
    (row,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    assert row["note"] == (
        "Auto-recorded from market data: a dividend of 0.25 EUR per share, dated the day after your "
        "balance of 2026-09-25, which did not hold it"
    )
    # Corrected with the statement's day and credit, it is counted once, and
    # not recorded again.
    r = client.put(f"/api/transactions/{row['id']}", json={
        "kind": "dividend", "date": PAID, "institution_id": iid, "asset_name": row["asset_name"],
        "symbol": TICKER, "quantity": 20, "unit_price": 0.185, "amount": None, "currency": "EUR",
        "price_currency": "EUR",
    })
    assert r.status_code == 200, r.text
    on("2026-10-06")
    assert (_created(_catch_up(client)), _cash(client, iid)) == ([], 5003.7)


def test_its_money_was_in_the_balance_so_it_counts_in_the_dividends_only(client, yahoo, on):
    iid = _two_situations(client)
    _catch_up(client)
    answered = _answer(client, iid, answer="in_balance", ex_date=EX, balance_date="2026-09-25")
    assert _created(answered) == [(EX, 5.0)]
    assert (_cash(client, iid), _collected(client)) == (5000.0, 5.0)


def test_a_balance_answer_for_a_balance_no_longer_the_latest_is_refused(client, yahoo, on):
    iid = _two_situations(client)
    _catch_up(client)
    r = client.post("/api/transactions/dividend-answer", json={
        "institution_id": iid, "symbol": TICKER, "answer": "after_balance", "ex_date": EX,
        "balance_date": "2026-06-01",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "The balance of 2026-06-01 is no longer the latest at Broker A: reload the page to see what is asked now."
    )
    assert _dividends(client) == []


def test_a_balance_typed_before_the_ex_date_cannot_hold_it(client, yahoo, on):
    """The situation of the 25th with its balance typed on the 20th: the
    money came after it whatever the payment date. Recorded on its ex-date,
    and counted in the cash, with nothing asked."""
    iid = _account(client)
    _situation(client, iid, "2026-06-01")
    _balance(client, iid, "2026-09-20")
    _situation(client, iid, "2026-09-25")
    result = _catch_up(client)
    assert (_created(result), result["questions"]) == ([(EX, 5.0)], [])
    assert _cash(client, iid) == 5005.0


def test_a_row_recorded_on_its_ex_date_before_a_later_balance_is_corrected_to_its_day(client, yahoo, on):
    """The other side, as measured: recorded on the 22nd, then the situation
    and balance of the 25th, which do not hold it. The row is not asked about
    (the reader corrects it with the broker's credit anyway); corrected with
    the day it was paid, it is counted in the cash that follows, and stays."""
    iid = _account(client)
    _situation(client, iid, "2026-06-01")
    _balance(client, iid, "2026-06-01")
    on("2026-09-23")
    assert _created(_catch_up(client)) == [(EX, 5.0)]
    _situation(client, iid, "2026-09-25")
    _balance(client, iid, "2026-09-25")
    on("2026-10-05")
    result = _catch_up(client)
    assert (_created(result), result["questions"], _cash(client, iid)) == ([], [], 5000.0)
    (row,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    r = client.put(f"/api/transactions/{row['id']}", json={
        "kind": "dividend", "date": PAID, "institution_id": iid, "asset_name": row["asset_name"],
        "symbol": TICKER, "quantity": 20, "unit_price": 0.185, "amount": None, "currency": "EUR",
        "price_currency": "EUR",
    })
    assert r.status_code == 200, r.text
    assert (_created(_catch_up(client)), _cash(client, iid)) == ([], 5003.7)


# --- Every stretch (the reader's D4) -----------------------------------------------------------


def test_a_dividend_inside_an_earlier_stretch_is_recorded_once(client, yahoo, on):
    """Found beside the third defect, as measured: ex-dates of 10 July and 22
    September, situations of 1 June and 25 September, the balance of the 25th
    holding July's credit. July's window ends on 22 September, before the
    balance, so its money is in it: recorded on its ex-date, counted in the
    dividends collected and not again in the cash. September's is asked."""
    yahoo.listed = [("2026-07-10", 0.25), (EX, 0.25)]
    iid = _account(client)
    _situation(client, iid, "2026-06-01")
    _balance(client, iid, "2026-06-01")
    _situation(client, iid, "2026-09-25")
    _balance(client, iid, "2026-09-25", 5003.70)
    result = _catch_up(client)
    assert _created(result) == [("2026-07-10", 5.0)]
    assert [q["dividends"][0]["ex_date"] for q in result["questions"]] == [EX]
    assert (_cash(client, iid), _collected(client)) == (5003.7, 5.0)
    on("2026-10-06")
    assert _created(_catch_up(client)) == []


def test_each_dividend_takes_the_units_of_its_own_stretch(client, yahoo, on):
    """Ten of the twenty units sold on 1 July: the dividend of 10 July is
    paid on ten. The units come from the situation before the ex-date and the
    ledger since, as they always did after the latest situation."""
    yahoo.listed = [("2026-07-10", 0.25)]
    iid = _account(client)
    _situation(client, iid, "2026-06-01")
    r = client.post("/api/transactions", json={
        "kind": "sell", "date": "2026-07-01", "institution_id": iid, "asset_name": "Example Dividend Share",
        "symbol": TICKER, "asset_class": "equity", "quantity": 10, "unit_price": 55, "currency": "EUR",
        "price_currency": "EUR",
    })
    assert r.status_code == 201, r.text
    _situation(client, iid, "2026-09-25", qty=10)
    assert _created(_catch_up(client)) == [("2026-07-10", 2.5)]


def test_a_stretch_whose_situation_did_not_hold_the_share_pays_nothing(client, yahoo, on):
    yahoo.listed = [("2026-07-10", 0.25)]
    iid = _account(client)
    client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-06-01"})
    _situation(client, iid, "2026-09-25")
    assert _created(_catch_up(client)) == []


# --- Before the account's first situation ------------------------------------------------------


def test_before_the_first_situation_the_question_says_whose_units(client, yahoo, on):
    """A first situation and balance typed on the 25th, three days after the
    ex-date: the app has no units for the 22nd but the first situation's, and
    says so in the question; answered, the row says so too."""
    iid = _account(client)
    _situation(client, iid, "2026-09-25")
    _balance(client, iid, "2026-09-25")
    (asked,) = _catch_up(client)["questions"]
    assert (asked["kind"], asked["first_situation"], asked["dividends"][0]["units"]) == (
        "in_balance", "2026-09-25", 20.0,
    )
    answered = _answer(client, iid, answer="after_balance", ex_date=EX, balance_date="2026-09-25")
    assert _created(answered) == [("2026-09-26", 5.0)]
    (row,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    assert row["note"].endswith(
        "dated the day after your balance of 2026-09-25, which did not hold it, for the 20 units of your "
        "first situation, of 2026-09-25"
    )
    assert (_cash(client, iid), _collected(client)) == (5005.0, 5.0)


def test_before_the_first_situation_with_no_balance_nothing_is_recorded(client, yahoo, on):
    """No balance its money could have come after: nothing it would count in,
    and nothing guessed about units held before the first situation."""
    iid = _account(client)
    _situation(client, iid, "2026-09-25")
    result = _catch_up(client)
    assert (_created(result), result["questions"]) == ([], [])


def test_before_the_first_situation_only_a_window_reaching_past_it_counts(client, yahoo, on):
    """Two quarterly dividends before a first situation of 25 September: June's
    window ends on 18 September, the next ex-date, so its money is older than
    the account's first balance and nothing is asked; September's is."""
    yahoo.listed = [("2026-06-20", 0.25), ("2026-09-18", 0.25)]
    iid = _account(client)
    _situation(client, iid, "2026-09-25")
    _balance(client, iid, "2026-09-25")
    result = _catch_up(client)
    assert _created(result) == []
    assert [q["dividends"][0]["ex_date"] for q in result["questions"]] == ["2026-09-18"]


# --- The history the catch-up keeps --------------------------------------------------------------


def test_the_kept_history_is_asked_once_from_a_year_before_the_first_situation(client, yahoo, on):
    """A history kept before this brief reached back only to the latest
    situation. The first catch-up after it asks once from a year before the
    account's first situation ("2y" here), merges, and then asks the day's
    window only, as before."""
    iid = _account(client)
    _situation(client, iid, "2026-06-01")
    _situation(client, iid, "2026-09-25")
    with SessionLocal() as db:
        db.add(models.Setting(
            key=f"dividends_asked:{TICKER}",
            value=f'{{"on":"2026-10-04","since":"2026-09-25","dividends":[{{"date":"{EX}","dps":0.25}}],"last":"{EX}"}}',
        ))
        db.commit()
    _catch_up(client)
    on("2026-10-06")
    _catch_up(client)
    assert yahoo.asked == [(TICKER, "2y"), (TICKER, "1mo")]


def test_a_day_s_window_never_drops_what_the_kept_history_holds(client, yahoo, on):
    """The first answer, the whole history, lists July; the next day's window
    reaches back only to the latest situation and lists September alone. July
    stays kept, and stays recorded once."""
    yahoo.listed = [("2026-07-10", 0.25), (EX, 0.25)]
    iid = _account(client)
    _situation(client, iid, "2026-06-01")
    _situation(client, iid, "2026-09-25")
    _catch_up(client)
    yahoo.listed = [(EX, 0.25)]
    on("2026-10-06")
    _catch_up(client)
    with SessionLocal() as db:
        kept = db.scalar(select(models.Setting.value).where(models.Setting.key == f"dividends_asked:{TICKER}"))
    assert '"2026-07-10"' in kept and f'"{EX}"' in kept
    assert [d[0] for d in _dividends(client)] == ["2026-07-10", EX]
