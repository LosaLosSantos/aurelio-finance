"""A currency the ECB does not publish is converted at Yahoo's rate, where a
trustworthy one exists (brief BA, the reader's decision D1).

Measured at 279acf8: every rate came from the ECB, so an amount in TWD, AED
or VND converted to nothing and was counted as written, a balance of 700 TWD
read as 700.00 EUR. Yahoo's daily close of `USD{code}=X` is kept for such a
code and crossed at the ECB's dollar of the same day (`yahoo_rates`).

Yahoo is answered here by invented closes (`prices._fetch_close_window`
replaced), the ECB by 1.25 dollars per euro: 32 TWD a dollar is then 40 TWD a
euro, so the wrong day's close cannot pass for rounding. The days are fixed
past ones where a weekday matters: 2026-01-03 is a Saturday, 2025-12-26 a
Friday the ECB did not publish, and 2026-01-01 a day Yahoo keeps an empty row
for, as measured in P0.
"""

from __future__ import annotations

import datetime
import sqlite3
from contextlib import closing

import pytest
from alembic import command
from alembic.config import Config

from app import database, fx, models, prices, yahoo_rates
from app.database import SessionLocal
from tests.yahoo_chart import Listing, install

TODAY = datetime.date.today()
ECB_DAY = "2025-11-03"
REAL_FETCH_CLOSE_WINDOW = prices._fetch_close_window


def ago(n: int) -> str:
    return (TODAY - datetime.timedelta(days=n)).isoformat()


@pytest.fixture
def feed(monkeypatch):
    """The ECB: one day long ago, each base's dollar (and euro) quoted."""
    per_base = {
        "EUR": {"USD": 1.25, "GBP": 0.85},
        "GBP": {"USD": 1.4, "EUR": 1.15},
        "USD": {"EUR": 0.8, "GBP": 0.7},
    }
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {ECB_DAY: per_base.get(base, {})}
    )


class Yahoo:
    """Yahoo's dated window, answered from `closes` ({symbol: [(day, close)]}),
    every ask recorded. A pair it does not have answers no rows, as Yahoo's
    404 reaches the app."""

    def __init__(self):
        self.closes: dict[str, list[tuple[str, float | None]]] = {}
        self.asked: list[tuple[str, str, str]] = []

    def __call__(self, symbol, start, end):
        self.asked.append((symbol, start.isoformat(), end.isoformat()))
        rows = self.closes.get(symbol, [])
        return [(d, c) for d, c in rows if start.isoformat() <= d < end.isoformat()]


@pytest.fixture
def yahoo(monkeypatch):
    y = Yahoo()
    monkeypatch.setattr(prices, "_fetch_close_window", y)
    return y


def weekdays(first: str, last: str, close: float = 32.0, **on: float | None) -> list:
    """Every weekday from `first` to `last` at `close`, a day of `on` (written
    d2026_01_06=...) at its own close, None for Yahoo's empty row."""
    special = {k[1:].replace("_", "-"): v for k, v in on.items()}
    out = []
    day = datetime.date.fromisoformat(first)
    while day.isoformat() <= last:
        if day.weekday() < 5:
            out.append((day.isoformat(), special.get(day.isoformat(), close)))
        day += datetime.timedelta(days=1)
    return out


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


def _accounts(client) -> tuple[int, int]:
    """A euro account and a TWD one."""
    eur = _made(client.post("/api/institutions", json={"name": "Euro bank"}))["id"]
    twd = _made(client.post("/api/institutions", json={"name": "Taipei bank"}))["id"]
    return eur, twd


def _arrived(client, day: str, to_currency: str = "TWD"):
    eur, twd = _accounts(client)
    return client.post("/api/transfers", json={
        "date": day, "amount": 100.0, "currency": "EUR", "to_currency": to_currency,
        "from_institution_id": eur, "to_institution_id": twd})


def _asset(client, currency: str, value: float, day: str) -> None:
    made = _made(client.post("/api/real-assets", json={"name": f"Asset in {currency}", "currency": currency}))
    _made(client.post(f"/api/real-assets/{made['id']}/valuations", json={"date": day, "value": value}))


# --- Converted, with the ECB still the source of what it publishes ------------------------------


def test_a_currency_the_ecb_does_not_publish_converts_at_yahoos_dollar_close(client, feed, yahoo):
    """4,000 TWD at 32 a dollar and 1.25 dollars a euro is 100.00 EUR, and
    nothing is counted as written any more."""
    yahoo.closes["USDTWD=X"] = weekdays(ago(40), ago(1))
    _asset(client, "TWD", 4000.0, ago(30))

    summary = client.get("/api/dashboard/summary").json()
    assert summary["real_total"] == 100.0
    assert summary["unconverted"] == []
    assert {s for s, _, _ in yahoo.asked} == {"USDTWD=X"}


def test_the_ecb_stays_the_source_of_every_currency_it_publishes(client, feed, yahoo):
    """Yahoo is never asked about a code the ECB lists, the dollar included."""
    yahoo.closes["USDUSD=X"] = weekdays(ago(40), ago(1), close=99.0)
    _asset(client, "USD", 1000.0, ago(30))

    assert client.get("/api/dashboard/summary").json()["real_total"] == 800.0
    assert yahoo.asked == []


@pytest.mark.parametrize(
    "day, arrived, rate_day",
    [
        # A Saturday takes Friday's close.
        ("2026-01-03", 4100.0, "2026-01-02"),
        # Yahoo keeps an empty row for 1 January: the close in force is the 31st's.
        ("2026-01-01", 4050.0, "2025-12-31"),
        # The ECB did not publish on 26 December; Yahoo closed, and that close is its.
        ("2025-12-26", 3950.0, "2025-12-26"),
    ],
)
def test_a_weekend_and_a_holiday_take_the_close_in_force(client, feed, yahoo, day, arrived, rate_day):
    yahoo.closes["USDTWD=X"] = weekdays(
        "2025-12-01", "2026-01-30",
        d2025_12_25=None, d2025_12_26=31.6, d2025_12_31=32.4, d2026_01_01=None, d2026_01_02=32.8,
    )
    made = _made(_arrived(client, day))
    assert (made["to_amount"], made["fx_as_of"]) == (arrived, rate_day)


# --- Trusted only when ---------------------------------------------------------------------------


def test_a_print_off_both_its_neighbours_is_not_taken(client, feed, yahoo):
    """35.5 between 32.0 and 32.1: a print, measured 175 times in two years of
    the dollar pairs (P0). The day reads as having no close of its own."""
    yahoo.closes["USDTWD=X"] = weekdays(
        "2025-12-01", "2026-01-30", d2026_01_06=35.5, d2026_01_07=32.1
    )
    made = _made(_arrived(client, "2026-01-06"))
    assert (made["to_amount"], made["fx_as_of"]) == (4000.0, "2026-01-05")


def test_a_slip_is_not_taken_even_as_the_newest_close(client, feed, yahoo):
    """A hundredfold slip with no next close to judge it by is still more than
    50% from the median of the five closes ending on it."""
    yahoo.closes["USDTWD=X"] = weekdays("2025-12-01", "2026-01-08") + [("2026-01-09", 3200.0)]
    made = _made(_arrived(client, "2026-01-09"))
    assert (made["to_amount"], made["fx_as_of"]) == (4000.0, "2026-01-08")


def test_a_sum_on_a_day_that_moved_more_than_five_percent_waits_for_the_next_close(
    client, feed, yahoo
):
    """34.0 after 32.0 may be a print or a move: a sum fixed on that day waits
    for the next close, as before a day is over, and takes it once the next
    close says it held."""
    yahoo.closes["USDTWD=X"] = weekdays("2025-12-01", "2026-01-07") + [("2026-01-08", 34.0)]
    waits = _arrived(client, "2026-01-08")
    assert waits.status_code == 422
    assert waits.json()["detail"].startswith(
        "No final exchange rate from EUR to TWD is known for 2026-01-08 yet"
    )

    # The next close comes, and held: the same request takes 8 January's.
    yahoo.closes["USDTWD=X"].append(("2026-01-09", 34.1))
    eur, twd = (i["id"] for i in _made(client.get("/api/institutions")))
    made = _made(client.post("/api/transfers", json={
        "date": "2026-01-08", "amount": 100.0, "currency": "EUR", "to_currency": "TWD",
        "from_institution_id": eur, "to_institution_id": twd}))
    assert (made["to_amount"], made["fx_as_of"]) == (4250.0, "2026-01-08")


def test_a_sum_fixed_today_waits_for_todays_close(client, feed, yahoo):
    """Yahoo's row of a day under way is a price still moving: a sum fixed on
    today waits for the day to be over, though yesterday's close is kept. On
    a dollar base, where no ECB rate takes part and only Yahoo's close decides."""
    yahoo.closes["USDTWD=X"] = weekdays(ago(20), ago(1))
    with SessionLocal() as db:
        db.merge(models.Setting(key=fx.BASE_CURRENCY_KEY, value="USD"))
        db.commit()
    dollars, taipei = _accounts(client)
    waits = client.post("/api/transfers", json={
        "date": TODAY.isoformat(), "amount": 100.0, "currency": "USD", "to_currency": "TWD",
        "from_institution_id": dollars, "to_institution_id": taipei})
    assert waits.status_code == 422
    assert waits.json()["detail"].startswith(
        f"No final exchange rate from USD to TWD is known for {TODAY.isoformat()} yet"
    )
    # Yesterday's sum, on the same base, takes yesterday's close at once.
    yesterday = max(d for d, _ in yahoo.closes["USDTWD=X"])
    made = _made(client.post("/api/transfers", json={
        "date": yesterday, "amount": 100.0, "currency": "USD", "to_currency": "TWD",
        "from_institution_id": dollars, "to_institution_id": taipei}))
    assert (made["to_amount"], made["fx_as_of"]) == (3200.0, yesterday)


def test_a_close_older_than_seven_days_is_no_rate(client, feed, yahoo):
    """The longest gap between two honest closes was five days (Easter 2025)."""
    yahoo.closes["USDTWD=X"] = weekdays("2025-12-01", "2026-01-09")
    with SessionLocal() as db:
        assert fx.Converter(db, on="2026-01-16").to_base(4000.0, "TWD") == 100.0
        assert fx.Converter(db, on="2026-01-17").to_base(4000.0, "TWD") is None


def test_a_quote_with_no_history_is_no_source_and_asked_again_a_day_later(client, feed, yahoo):
    """Twenty currencies Yahoo quotes have no daily history (P0): a first
    window answering on one day only. Said as a currency no source quotes."""
    yahoo.closes["USDAMD=X"] = [(TODAY.isoformat(), 390.0)]
    _asset(client, "AMD", 39000.0, ago(30))

    (said,) = client.get("/api/dashboard/summary").json()["unconverted"]
    assert (said["currency"], said["not_a_code"], said["shares"]["real_total"]) == ("AMD", False, 39000.0)
    asked = len(yahoo.asked)
    client.get("/api/dashboard/summary")
    assert len(yahoo.asked) == asked, "asked once a day, not at every reading"

    with SessionLocal() as db:
        db.merge(models.Setting(
            key="fx_yahoo_no_daily_close:AMD",
            value=(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)).isoformat(),
        ))
        db.commit()
    client.get("/api/dashboard/summary")
    assert len(yahoo.asked) == asked + 1


def test_a_typo_is_never_asked_of_yahoo(client, feed, yahoo):
    _asset(client, "USD", 1000.0, ago(30))
    with SessionLocal() as db:
        db.execute(models.RealAsset.__table__.update().values(currency="Doll"))
        db.commit()
    (said,) = client.get("/api/dashboard/summary").json()["unconverted"]
    assert (said["currency"], said["not_a_code"]) == ("Doll", True)
    assert yahoo.asked == []


# --- Neither source quotes it ---------------------------------------------------------------------


def test_a_code_neither_source_quotes_is_said_so_and_without_a_yet(client, feed, yahoo):
    """BTN: real, published by neither (P0). Measured at 279acf8, a transfer
    to it answered "No final exchange rate from EUR to TWD is known for
    2026-10-11 yet": a rate that would never come."""
    refused = _arrived(client, "2026-01-05", to_currency="BTN")
    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        "No source quotes a rate for BTN, neither the ECB nor Yahoo, so what reached the "
        "destination cannot be worked out in BTN. State the amount that arrived: the figure "
        "on the destination account's statement."
    )
    eur = _made(client.get("/api/institutions"))[0]["id"]
    buy = client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-01-05", "institution_id": eur, "asset_name": "Invented Thimphu share",
        "symbol": "ZZBT.XX", "quantity": 1, "unit_price": 1000.0, "currency": "EUR", "price_currency": "BTN"})
    assert buy.status_code == 422
    assert buy.json()["detail"] == (
        "No source quotes a rate for BTN, neither the ECB nor Yahoo, so the buy cannot be "
        "worked out in EUR. State the amount from your statement. That is the figure the "
        "account actually moved by."
    )


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError])
def test_a_transport_failure_does_not_certify_a_cached_rate_or_suppress_retry(
    client, feed, monkeypatch, tmp_path, cached, failure
):
    monkeypatch.setattr(prices, "_fetch_close_window", REAL_FETCH_CLOSE_WINDOW)
    chart = install(monkeypatch, tmp_path)
    chart.listings["USDTWD=X"] = Listing(
        closes={"2026-01-06": 32.0, "2026-01-07": 32.0, "2026-01-09": 33.0},
        currency="TWD", timezone="UTC",
    )
    now = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
    before = datetime.datetime(2026, 1, 8, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(yahoo_rates, "_now", lambda: now)
    if cached:
        with SessionLocal() as db:
            yahoo_rates._asked_back(db, "TWD", datetime.date(2025, 12, 1))
            yahoo_rates._store(
                db, "TWD", [("2026-01-06", 32.0), ("2026-01-07", 32.0)],
                before, asked_for_newer=True,
            )
    answer = chart.answer

    def unavailable(url, params):
        if "period1" in params:
            raise failure("Yahoo transport unavailable")
        return answer(url, params)

    monkeypatch.setattr(chart, "answer", unavailable)
    refused = _arrived(client, "2026-01-09")
    assert refused.status_code == 422
    assert refused.json()["detail"].startswith(
        "No final exchange rate from EUR to TWD is known for 2026-01-09 yet"
    )
    assert client.get("/api/transfers").json() == []
    with SessionLocal() as db:
        assert yahoo_rates._stamp(db, yahoo_rates._ASKED.format(code="TWD")) == (
            before if cached else None
        )
        assert db.get(models.Setting, yahoo_rates._NO_HISTORY.format(code="TWD")) is None
        assert not yahoo_rates.final(db, "TWD", "2026-01-09", "2026-01-07")
        back = db.get(models.Setting, yahoo_rates._BACK.format(code="TWD"))
        assert (back.value if back else None) == ("2025-12-01" if cached else None)

    monkeypatch.setattr(chart, "answer", answer)
    eur, twd = (i["id"] for i in _made(client.get("/api/institutions")))
    made = _made(client.post("/api/transfers", json={
        "date": "2026-01-09", "amount": 100.0, "currency": "EUR", "to_currency": "TWD",
        "from_institution_id": eur, "to_institution_id": twd,
    }))
    assert (made["to_amount"], made["fx_as_of"]) == (4125.0, "2026-01-09")
    (stored,) = client.get("/api/transfers").json()
    assert (stored["to_amount"], stored["fx_as_of"]) == (4125.0, "2026-01-09")


def test_a_successful_empty_yahoo_history_still_marks_a_code_as_unquoted(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(prices, "_fetch_close_window", REAL_FETCH_CLOSE_WINDOW)
    chart = install(monkeypatch, tmp_path)
    chart.listings["USDBTN=X"] = Listing(closes={}, currency="BTN", timezone="UTC")
    with SessionLocal() as db:
        yahoo_rates.ensure(db, "BTN", ["2026-01-09"])
        assert yahoo_rates.no_source(db, "BTN")
        assert db.get(models.Setting, yahoo_rates._ASKED.format(code="BTN")) is None
        assert db.get(models.Setting, yahoo_rates._BACK.format(code="BTN")) is None
        asked = len(chart.asked)
        yahoo_rates.ensure(db, "BTN", ["2026-01-09"])
        assert len(chart.asked) == asked


def test_the_catch_up_says_no_source_quotes_a_plans_code(client, feed, yahoo, monkeypatch):
    monkeypatch.setattr(prices, "get_price_on",
                        lambda symbol, on: {"symbol": symbol, "price": 1000.0, "as_of": on.isoformat()})
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "BTN")
    eur, _ = _accounts(client)
    _made(client.post(f"/api/institutions/{eur}/cash-anchors",
                      json={"date": "2025-12-01", "amount": 1000.0, "currency": "EUR"}))
    _made(client.post("/api/accumulation-plans", json={
        "name": "Invented plan", "amount": 250.0, "currency": "EUR", "frequency": "annual",
        "start_date": "2026-01-05", "source_institution_id": eur,
        "targets": [{"symbol": "ZZBT.XX", "asset_name": "Invented Thimphu share", "institution_id": eur}]}))

    answer = _made(client.post("/api/transactions/catch-up"))
    (skipped,) = answer["skipped"]
    assert skipped["reason"] == (
        "ZZBT.XX: no source quotes a rate for BTN, neither the ECB nor Yahoo, so its price "
        "cannot be set against the plan's budget"
    )


# --- Any base, the history, the catch-up ----------------------------------------------------------


@pytest.mark.parametrize("base, value, total", [("GBP", 4480.0, 100.0), ("USD", 3200.0, 100.0)])
def test_another_base_crosses_at_the_ecbs_dollar_of_that_base(client, feed, yahoo, base, value, total):
    """32 TWD a dollar: 44.8 a pound at the ECB's 1.4 dollars a pound, and 32
    a dollar for a dollar base, with no ECB leg at all."""
    yahoo.closes["USDTWD=X"] = weekdays(ago(40), ago(1))
    with SessionLocal() as db:
        db.merge(models.Setting(key=fx.BASE_CURRENCY_KEY, value=base))
        db.commit()
    _asset(client, "TWD", value, ago(30))

    summary = client.get("/api/dashboard/summary").json()
    assert (summary["base_currency"], summary["real_total"]) == (base, total)


def test_the_history_converts_each_point_and_asks_yahoo_once(client, feed, yahoo):
    """Each point at the close in force on its own day, the window asked once
    from ten days before the first point."""
    yahoo.closes["USDTWD=X"] = weekdays(ago(90), ago(46), close=40.0) + weekdays(ago(45), ago(1), close=32.0)
    twd = _made(client.post("/api/institutions", json={"name": "Taipei bank"}))["id"]
    _made(client.post(f"/api/institutions/{twd}/cash-anchors",
                      json={"date": ago(60), "amount": 5000.0, "currency": "TWD"}))
    euro = _made(client.post("/api/institutions", json={"name": "Euro bank"}))["id"]
    _made(client.post(f"/api/institutions/{euro}/cash-anchors",
                      json={"date": ago(30), "amount": 0.0, "currency": "EUR"}))

    series = client.get("/api/dashboard/net-worth-series").json()
    by_day = {p["date"]: p for p in series}
    # 5,000 TWD at 40 a dollar then (50 a euro), at 32 later (40 a euro).
    assert by_day[ago(60)]["net_worth"] == 100.0
    assert by_day[ago(30)]["net_worth"] == 125.0
    assert all(p["unconverted"] == [] for p in series)
    windows = [(s, start) for s, start, _ in yahoo.asked]
    assert windows[0] == ("USDTWD=X", (TODAY - datetime.timedelta(days=70)).isoformat())
    asked = len(yahoo.asked)
    client.get("/api/dashboard/net-worth-series")
    assert len(yahoo.asked) == asked


def test_days_before_yahoos_history_are_asked_about_once(client, feed, yahoo):
    """TWD's daily history at Yahoo starts in 2006 (P0): a reading of a day
    before it asks once, not at every page, and that day's amount is said as
    counted as written."""
    yahoo.closes["USDTWD=X"] = weekdays(ago(40), ago(1))
    twd = _made(client.post("/api/institutions", json={"name": "Taipei bank"}))["id"]
    _made(client.post(f"/api/institutions/{twd}/cash-anchors",
                      json={"date": ago(400), "amount": 5000.0, "currency": "TWD"}))
    euro = _made(client.post("/api/institutions", json={"name": "Euro bank"}))["id"]
    _made(client.post(f"/api/institutions/{euro}/cash-anchors",
                      json={"date": ago(30), "amount": 0.0, "currency": "EUR"}))

    series = client.get("/api/dashboard/net-worth-series").json()
    assert [(p["date"], p["unconverted"]) for p in series] == [
        (ago(400), ["TWD"]), (ago(30), []), (TODAY.isoformat(), []),
    ]
    asked = len(yahoo.asked)
    client.get("/api/dashboard/net-worth-series")
    assert len(yahoo.asked) == asked


def test_a_plan_buys_a_taipei_listing_at_yahoos_close_of_its_day(client, feed, yahoo, monkeypatch):
    """A plan in euro, a target quoted in TWD: 500 TWD a unit at 40 TWD a
    euro is 12.50 EUR, so 250.00 buys 20 units, at the rate of 2026-01-05."""
    yahoo.closes["USDTWD=X"] = weekdays("2025-12-01", "2026-01-30")
    monkeypatch.setattr(prices, "get_price_on",
                        lambda symbol, on: {"symbol": symbol, "price": 500.0, "as_of": on.isoformat()})
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "TWD")
    eur, _ = _accounts(client)
    _made(client.post(f"/api/institutions/{eur}/cash-anchors",
                      json={"date": "2025-12-01", "amount": 1000.0, "currency": "EUR"}))
    _made(client.post("/api/accumulation-plans", json={
        "name": "Invented plan", "amount": 250.0, "currency": "EUR", "frequency": "annual",
        "start_date": "2026-01-05", "source_institution_id": eur,
        "targets": [{"symbol": "ZZTW.TW", "asset_name": "Invented Taipei share", "institution_id": eur}]}))

    answer = _made(client.post("/api/transactions/catch-up"))
    assert answer["skipped"] == []
    (buy,) = client.get("/api/transactions").json()
    assert (buy["quantity"], buy["unit_price"], buy["price_currency"], buy["amount"], buy["currency"],
            buy["fx_as_of"]) == (20.0, 500.0, "TWD", 250.0, "EUR", "2026-01-05")


# --- The migration --------------------------------------------------------------------------------


@pytest.fixture
def before_yahoo(tmp_path, start_on):
    """A file the real chain built up to `0e29ce42774e`, the revision before
    this one, with two of the ECB's rates."""
    path = tmp_path / "data.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(cfg, "0e29ce42774e")
    with closing(sqlite3.connect(path)) as conn, conn:
        for currency, rate in (("USD", 1.25), ("GBP", 0.85)):
            conn.execute(
                "INSERT INTO fx_rates (base, currency, as_of, rate, fetched_at)"
                " VALUES ('EUR', ?, '2026-10-15', ?, '2026-10-15T16:00:00')",
                (currency, rate),
            )
    start_on(path)
    return path


def test_the_migration_creates_one_table_and_touches_no_row(before_yahoo):
    path = before_yahoo
    rates = "SELECT base, currency, as_of, rate, fetched_at FROM fx_rates ORDER BY currency"
    with closing(sqlite3.connect(path)) as conn:
        before = conn.execute(rates).fetchall()

    database.init_db()

    assert len(list(path.parent.glob("data.db.bak-*-before-migration-0e29ce42774e-to-*"))) == 1, (
        "the app copied the file before migrating it"
    )
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute(rates).fetchall() == before
        columns = {row[1]: (row[2], row[3], row[5]) for row in conn.execute("PRAGMA table_info(fx_rates_yahoo)")}
        assert columns == {
            "currency": ("VARCHAR", 1, 1),
            "as_of": ("VARCHAR", 1, 2),
            "rate": ("FLOAT", 1, 0),
            "fetched_at": ("VARCHAR", 1, 0),
        }
        assert conn.execute("SELECT COUNT(*) FROM fx_rates_yahoo").fetchone() == (0,)

    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    command.downgrade(cfg, "0e29ce42774e")
    with closing(sqlite3.connect(path)) as conn, conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "fx_rates_yahoo" not in tables
        assert conn.execute(rates).fetchall() == before


def test_the_rules_thresholds_are_the_measured_ones():
    """What P0 measured them from is in `yahoo_rates`' docstring; a change to
    one is a change to the counts said beside it."""
    assert (yahoo_rates.SLIP, yahoo_rates.SPIKE, yahoo_rates.NEIGHBOURS_AGREE,
            yahoo_rates.STALE_DAYS) == (0.50, 0.05, 0.025, 7)


# --- Whose rate, said wherever its day is said (part 5) -------------------------------------------


def test_a_ledger_row_and_a_transfer_say_whose_rate_they_took(client, feed, yahoo):
    """Measured at 279acf8, every row's rate was said as "the ECB rate of": a
    day alone no longer says whose."""
    yahoo.closes["USDTWD=X"] = weekdays("2025-12-01", "2026-01-30")
    eur, twd = _accounts(client)
    _made(client.post("/api/transfers", json={
        "date": "2026-01-05", "amount": 100.0, "currency": "EUR", "to_currency": "TWD",
        "from_institution_id": eur, "to_institution_id": twd}))
    _made(client.post("/api/transfers", json={
        "date": "2026-01-05", "amount": 100.0, "currency": "EUR", "to_currency": "USD",
        "from_institution_id": eur, "to_institution_id": twd}))
    assert sorted((t["to_currency"], t["fx_as_of"], t["fx_source"])
                  for t in client.get("/api/transfers").json()) == [
        ("TWD", "2026-01-05", "Yahoo"), ("USD", ECB_DAY, "ECB"),
    ]
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-01-05", "institution_id": eur, "asset_name": "Invented Taipei share",
        "symbol": "ZZTW.TW", "quantity": 2, "unit_price": 500.0, "currency": "EUR", "price_currency": "TWD"}))
    (row,) = client.get("/api/transactions").json()
    assert (row["amount"], row["fx_as_of"], row["fx_source"]) == (25.0, "2026-01-05", "Yahoo")


def test_the_portfolio_and_the_history_say_yahoos_day_beside_the_ecbs(client, feed, yahoo):
    yahoo.closes["USDTWD=X"] = weekdays(ago(40), ago(1))
    broker = _made(client.post("/api/institutions", json={"name": "Taipei broker"}))["id"]
    sid = _made(client.post(f"/api/institutions/{broker}/snapshots", json={"date": ago(30)}))["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings",
                      json={"asset_name": "Fund in TWD", "value": 4000.0, "currency": "TWD"}))
    last_close = max(d for d, _ in yahoo.closes["USDTWD=X"])

    portfolio = client.get("/api/dashboard/portfolio").json()
    assert (portfolio["total_book"], portfolio["fx_as_of"], portfolio["fx_yahoo_as_of"]) == (
        100.0, ECB_DAY, last_close,
    )
    today = client.get("/api/dashboard/net-worth-series").json()[-1]
    assert (today["fx_as_of"], today["fx_yahoo_as_of"]) == (ECB_DAY, last_close)


@pytest.mark.parametrize("base, book, ecb_day", [("EUR", 100.0, ECB_DAY), ("USD", 125.0, None)])
def test_an_outside_assistant_is_told_yahoos_day_beside_the_ecbs(client, feed, yahoo, base, book, ecb_day):
    """The MCP server's positions said one day, read as the day of every rate
    and null "when nothing needed converting": with a dollar base a holding in
    TWD takes Yahoo's close alone, and that day read null. Read-only, the
    server serves the closes the app kept."""
    from app.mcp_server import build_server
    from tests.test_mcp_server import _call, _db_file

    yahoo.closes["USDTWD=X"] = weekdays(ago(40), ago(1))
    with SessionLocal() as db:
        db.merge(models.Setting(key=fx.BASE_CURRENCY_KEY, value=base))
        db.commit()
    broker = _made(client.post("/api/institutions", json={"name": "Taipei broker"}))["id"]
    sid = _made(client.post(f"/api/institutions/{broker}/snapshots", json={"date": ago(30)}))["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings",
                      json={"asset_name": "Fund in TWD", "value": 4000.0, "currency": "TWD"}))
    _made(client.get("/api/dashboard/portfolio"))
    last_close = max(d for d, _ in yahoo.closes["USDTWD=X"])

    body = _call(build_server(_db_file()), "get_positions")
    (row,) = body["positions"]
    assert (row["book_value"], body["rates_as_of"], body["yahoo_rates_as_of"]) == (book, ecb_day, last_close)
    assert "`yahoo_rates_as_of`" in body["reading"]


def test_the_chat_is_told_whose_rate(client, feed, yahoo):
    """Its rates line, its ledger lines and its cards' receipts."""
    from app import advisor, tools

    yahoo.closes["USDTWD=X"] = weekdays("2025-12-01", ago(1))
    eur, twd = _accounts(client)
    _made(client.post(f"/api/institutions/{eur}/cash-anchors",
                      json={"date": ago(30), "amount": 1000.0, "currency": "USD"}))
    _made(client.post(f"/api/institutions/{twd}/cash-anchors",
                      json={"date": ago(30), "amount": 4000.0, "currency": "TWD"}))
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-01-05", "institution_id": eur, "asset_name": "Invented Taipei share",
        "symbol": "ZZTW.TW", "quantity": 2, "unit_price": 500.0, "currency": "EUR", "price_currency": "TWD"}))
    _made(client.post(f"/api/institutions/{twd}/cash-anchors",
                      json={"date": ago(20), "amount": 4000.0, "currency": "BTN"}))
    last_close = max(d for d, _ in yahoo.closes["USDTWD=X"])

    with SessionLocal() as db:
        picture = advisor.build_context(db)
    (rates,) = [line for line in picture.split("\n") if line.startswith("Exchange rates:")]
    assert rates.endswith(
        f"1 EUR = 1.25 USD. For currencies the ECB does not publish, Yahoo's closes of "
        f"{last_close}, crossed at the ECB's dollar: 1 EUR = 40 TWD. No source quotes a "
        "rate for BTN, neither the ECB nor Yahoo."
    )
    assert "buy 2 x ZZTW.TW" in picture and "at the Yahoo rate of 2026-01-05" in picture
    assert tools._rate_field({"fx_as_of": "2026-01-05", "fx_source": "Yahoo"}) == (
        "At the Yahoo rate of", "2026-01-05", "date",
    )
