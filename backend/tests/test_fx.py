"""FX conversion (ECB rates): caching, the lazy converter, and the
multi-currency portfolio/summary behavior. Network is monkeypatched."""

from __future__ import annotations

import datetime

from sqlalchemy import select

from app import analytics, fx, models, prices
from app.database import READ_ONLY, SessionLocal

TODAY = datetime.date.today().isoformat()

RATES = {"2026-08-20": {"USD": 1.25, "GBP": 0.85}}


def _patch_rates(monkeypatch, payload=RATES):
    def fetch(base, start, end=None):
        assert base == "EUR", f"the converter asked for {base} rates"
        if isinstance(payload, Exception):
            raise payload
        return {day: dict(rates) for day, rates in payload.items()}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)


# --- fx module ---------------------------------------------------------------


def test_converter_math_and_lazy_loading(client, monkeypatch):
    calls = {"n": 0}

    def fetch(base, start, end=None):
        calls["n"] += 1
        return {"2026-08-20": {"USD": 1.25}}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    with SessionLocal() as db:
        conv = fx.Converter(db)
        # Amounts in the base never trigger a fetch — and neither does an
        # amount whose currency is not known, which is not read as the base.
        assert conv.to_base(100.0, "EUR") == 100.0
        assert conv.to_base(100.0, None) is None
        assert calls["n"] == 0
        # first USD amount loads the rates: 125 USD / 1.25 = 100 EUR
        assert conv.to_base(125.0, "usd") == 100.0
        assert calls["n"] == 1 and conv.used_as_of == "2026-08-20"
        # unknown currency -> None, caller decides
        assert conv.to_base(100.0, "JPY") is None


def test_rates_cached_within_ttl_and_stale_served_on_failure(client, monkeypatch):
    _patch_rates(monkeypatch)
    with SessionLocal() as db:
        assert fx.rates_on(db, "EUR", TODAY)["USD"]["rate"] == 1.25

    # feed down -> cached rates keep serving
    def boom(base, start, end=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(fx, "_fetch_rates", boom)
    with SessionLocal() as db:
        assert fx.rates_on(db, "EUR", TODAY)["USD"]["rate"] == 1.25  # fresh cache, no call
        assert fx.rates_on(db, "EUR", TODAY, refresh=True)["USD"]["rate"] == 1.25  # stale-serve


def test_fx_rates_endpoint(client, monkeypatch):
    _patch_rates(monkeypatch)
    body = client.get("/api/fx/rates").json()
    usd = next(r for r in body if r["currency"] == "USD")
    assert usd["rate"] == 1.25 and usd["as_of"] == "2026-08-20"
    assert usd["base"] == "EUR"


# --- a rate belongs to the base it was fetched against -------------------------

# Both sides of one pair, as the feed returned them for 2026-09-11 when asked
# with base=EUR and with base=USD. Neither answer lists its own base.
EUR_BASED = {"USD": 1.1592, "GBP": 0.85815}
USD_BASED = {"EUR": 0.86266, "GBP": 0.7403}


def _cache(db, base, rates, day="2026-09-11", fetched_at=None):
    """What a fetch with no end leaves behind: the day's rows, and the moment
    the feed was asked for newer days — both at `fetched_at`."""
    stamp = fetched_at or models._utcnow_iso()
    for cur, rate in rates.items():
        db.add(models.FxRate(base=base, currency=cur, rate=rate, as_of=day, fetched_at=stamp))
    db.merge(models.Setting(key=fx._ASKED_FOR_NEWER.format(base=base), value=stamp))
    db.commit()


def _record_feed(monkeypatch, answer=None) -> list[tuple]:
    """The ranges the feed was asked for, as (base, start, end). Recorded rather
    than raised: `rates_on` catches every exception from the feed and serves
    what is stored, so a fake that raised would be swallowed and a test built
    on it could not tell a call that happened from one that did not."""
    asked: list[tuple] = []

    def fetch(base, start, end=None):
        asked.append((base, start, end))
        return {day: dict(rates) for day, rates in (answer or {}).items()}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    return asked


def test_two_bases_sit_side_by_side_and_neither_is_read_for_the_other(client, monkeypatch):
    """The failure this key exists to prevent: one table, two bases, and a
    read that does not ask which. Without the filter the EUR read comes back
    with an "EUR" rate of 0.86266 — a rate for the base against itself, which
    the feed never gives and which only the other base's rows could supply."""
    asked = _record_feed(monkeypatch)
    with SessionLocal() as db:
        _cache(db, "EUR", EUR_BASED)
        _cache(db, "USD", USD_BASED)

        eur = fx.rates_on(db, "EUR", TODAY)
        usd = fx.rates_on(db, "USD", TODAY)

    assert {c: r["rate"] for c, r in eur.items()} == EUR_BASED
    assert {c: r["rate"] for c, r in usd.items()} == USD_BASED
    assert asked == []  # both caches fresh: nothing to fetch


def test_a_fresh_cache_for_one_base_does_not_make_another_look_fresh(client, monkeypatch):
    """Freshness is a property of one base's rows. A table that counted every
    row would find the EUR rates fetched a minute ago, call the cache fresh,
    and hand a USD caller nothing — for 24 hours, every time."""
    asked = _record_feed(monkeypatch, answer={"2026-09-11": USD_BASED})
    with SessionLocal() as db:
        _cache(db, "EUR", EUR_BASED)  # fetched just now: fresh by any clock
        before = {
            (r.currency, r.rate, r.fetched_at)
            for r in db.scalars(select(models.FxRate).where(models.FxRate.base == "EUR"))
        }

        usd = fx.rates_on(db, "USD", TODAY)

        after = {
            (r.currency, r.rate, r.fetched_at)
            for r in db.scalars(select(models.FxRate).where(models.FxRate.base == "EUR"))
        }

    assert [base for base, _, _ in asked] == ["USD"]
    assert {c: r["rate"] for c, r in usd.items()} == USD_BASED
    # The refresh of one base leaves the other's rows exactly as they were.
    assert after == before


def test_a_reader_that_cannot_write_serves_only_its_own_base(client, monkeypatch):
    """The MCP server's session cannot refresh, so it serves what is stored —
    and what is stored for ANOTHER base is not what is stored for this one. An
    empty answer is honest: every non-base amount converts to None, and each
    caller already has a rule for that. Borrowed rows would be a wrong answer
    that looks like a right one."""
    asked = _record_feed(monkeypatch)
    with SessionLocal() as db:
        _cache(db, "EUR", EUR_BASED)
        db.info[READ_ONLY] = True

        assert fx.rates_on(db, "USD", TODAY) == {}
        assert {c: r["rate"] for c, r in fx.rates_on(db, "EUR", TODAY).items()} == EUR_BASED

    # Not merely an empty answer: a reader that cannot store what it fetches
    # does not go and fetch it.
    assert asked == []


def test_the_rates_endpoint_lists_only_the_base_it_converts_to(client, monkeypatch):
    _record_feed(monkeypatch)
    with SessionLocal() as db:
        _cache(db, "EUR", EUR_BASED)
        _cache(db, "USD", USD_BASED)

    body = client.get("/api/fx/rates").json()

    assert {(r["base"], r["currency"], r["rate"]) for r in body} == {
        ("EUR", c, rate) for c, rate in EUR_BASED.items()
    }


# --- a rate is kept for its day ---------------------------------------------
#
# The table is the history of the rates, and `rates_on` is its one reading.
# Days below are real ECB days measured on 2026-09-15: 2026-06-12 is a Friday
# and 2026-06-15 the Monday after it; 2025-12-31 is the last day the lev (BGN)
# was published.

LONG_AGO = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).isoformat()


def test_a_day_with_no_publication_takes_the_working_day_before_it(client, monkeypatch):
    """A Saturday is converted at Friday's rate, and Monday at Monday's — the
    rule the feed itself answers by. With a later day stored, the history
    already says nothing was published in between, so nothing is fetched."""
    asked = _record_feed(monkeypatch)
    with SessionLocal() as db:
        _cache(db, "EUR", {"USD": 1.15}, day="2026-06-12")
        _cache(db, "EUR", {"USD": 1.16}, day="2026-06-15")

        saturday = fx.rates_on(db, "EUR", "2026-06-13")
        monday = fx.rates_on(db, "EUR", "2026-06-15")

    assert saturday["USD"] == {"rate": 1.15, "as_of": "2026-06-12"}
    assert monday["USD"] == {"rate": 1.16, "as_of": "2026-06-15"}
    assert asked == []


def test_a_currency_that_day_does_not_list_is_not_borrowed_from_an_older_one(
    client, monkeypatch
):
    """The day in force is chosen whole. The ECB last published the lev on
    2025-12-31; a reading of 5 January that went looking for the latest BGN
    rate on its own would convert at a rate from the previous year while
    reporting a day in January."""
    _record_feed(monkeypatch)
    with SessionLocal() as db:
        _cache(db, "EUR", {"USD": 1.1750, "BGN": 1.95583}, day="2025-12-31")
        _cache(db, "EUR", {"USD": 1.1739}, day="2026-01-02")

        january = fx.rates_on(db, "EUR", "2026-01-05")

    assert january == {"USD": {"rate": 1.1739, "as_of": "2026-01-02"}}


def test_a_day_older_than_the_history_is_fetched_once_and_joins_it(client, monkeypatch):
    """The feed is asked for the range from that day to the oldest stored one,
    so the history stays contiguous — and a day inside the range is then
    answered from what is stored."""
    asked = _record_feed(
        monkeypatch,
        answer={"2026-05-29": {"USD": 1.12}, "2026-06-01": {"USD": 1.13}, "2026-06-15": {"USD": 1.16}},
    )
    with SessionLocal() as db:
        _cache(db, "EUR", {"USD": 1.16}, day="2026-06-15")

        first = fx.rates_on(db, "EUR", "2026-05-31")  # a Sunday
        inside = fx.rates_on(db, "EUR", "2026-06-05")

    assert asked == [("EUR", "2026-05-31", "2026-06-15")]
    assert first["USD"] == {"rate": 1.12, "as_of": "2026-05-29"}
    assert inside["USD"] == {"rate": 1.13, "as_of": "2026-06-01"}


def test_the_newest_day_is_checked_forward_once_a_day(client, monkeypatch):
    """When the day in force is the newest one stored, a newer publication
    cannot be ruled out without asking — so the feed is asked from that day on,
    and asked at most once in 24 hours."""
    asked = _record_feed(
        monkeypatch, answer={"2026-06-15": {"USD": 1.16}, "2026-06-16": {"USD": 1.17}}
    )
    with SessionLocal() as db:
        _cache(db, "EUR", {"USD": 1.16}, day="2026-06-15", fetched_at=LONG_AGO)

        stale = fx.rates_on(db, "EUR", TODAY)
        again = fx.rates_on(db, "EUR", TODAY)

    assert asked == [("EUR", "2026-06-15", None)]
    assert stale["USD"] == again["USD"] == {"rate": 1.17, "as_of": "2026-06-16"}
    with SessionLocal() as db:
        # The day that was already stored is kept, not overwritten by the next.
        assert fx.rates_on(db, "EUR", "2026-06-15")["USD"]["rate"] == 1.16


def test_a_reader_that_cannot_write_answers_only_from_the_days_it_has(client, monkeypatch):
    asked = _record_feed(monkeypatch, answer={"2026-06-01": {"USD": 1.13}})
    with SessionLocal() as db:
        _cache(db, "EUR", {"USD": 1.16}, day="2026-06-15", fetched_at=LONG_AGO)
        db.info[READ_ONLY] = True

        assert fx.rates_on(db, "EUR", "2026-06-05") == {}
        assert fx.rates_on(db, "EUR", TODAY)["USD"] == {"rate": 1.16, "as_of": "2026-06-15"}

    assert asked == []


# --- portfolio & aggregates in multiple currencies -----------------------------


def _usd_stock(client, qty=10, unit_price=100):
    """A USD-quoted stock position (e.g. Walmart)."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Walmart", "asset_class": "equity", "symbol": "WMT",
              "quantity": qty, "unit_price": unit_price, "currency": "EUR"},
    )
    return iid


def test_usd_market_value_is_converted_to_eur(client, monkeypatch):
    _usd_stock(client, qty=10, unit_price=40)  # book 400 (EUR by default)
    _patch_rates(monkeypatch)
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 50.0, "as_of": "2026-08-20"} for s in syms},
    )
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "USD" for s in syms})

    p = client.get("/api/dashboard/portfolio", params={"live": "true"}).json()
    row = p["rows"][0]
    assert row["currency"] == "USD" and row["live_price"] == 50.0
    assert row["market_value"] == 400.0  # 10 * 50 USD / 1.25 = 400 EUR
    assert p["fx_as_of"] == "2026-08-20"

    # currency persisted in the price cache -> non-live reads convert too
    p2 = client.get("/api/dashboard/portfolio").json()
    assert p2["rows"][0]["market_value"] == 400.0


def test_unknown_rate_leaves_row_unpriced(client, monkeypatch):
    _usd_stock(client)
    _patch_rates(monkeypatch, {"2026-08-20": {"GBP": 0.85}})  # no USD
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 50.0, "as_of": "2026-08-20"} for s in syms},
    )
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "USD" for s in syms})

    p = client.get("/api/dashboard/portfolio", params={"live": "true"}).json()
    row = p["rows"][0]
    # no EUR rate for USD -> honest: no market value, not a mixed-currency sum
    assert row["market_value"] is None and row["live_price"] is None
    assert p["total_market"] is None


def test_holding_book_currency_converts_in_summary_and_portfolio(client, monkeypatch):
    """A holding whose recorded value is in USD converts at the ECB rate."""
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "US stock", "asset_class": "equity", "value": 125,
              "currency": "USD"},
    )
    _patch_rates(monkeypatch)

    p = client.get("/api/dashboard/portfolio").json()
    assert p["rows"][0]["book_value"] == 100.0  # 125 USD / 1.25
    assert p["total_book"] == 100.0
    assert client.get("/api/dashboard/summary").json()["investments_total"] == 100.0


def test_a_converted_book_value_carries_its_rate_date(client, monkeypatch):
    """[09] A number restated at an ECB rate has to say which rate.

    Nothing here is priceable — no ticker, no quantity — so the only FX work in
    the whole view is the book value. It used to be done by a converter the
    projection built for itself and threw away, while `fx_as_of` reported a
    SECOND converter that had converted nothing: 100 EUR on screen, derived
    from a rate, with no date attached to it. One converter now runs the
    projection and the pricing both."""
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "US stock", "asset_class": "equity", "value": 125,
              "currency": "USD"},
    )
    _patch_rates(monkeypatch)

    p = client.get("/api/dashboard/portfolio").json()
    assert p["rows"][0]["book_value"] == 100.0  # 125 USD / 1.25
    assert p["priced"] is False and p["prices_as_of"] is None
    assert p["fx_as_of"] == "2026-08-20"


def test_refresh_price_does_not_rewrite_a_stated_currency(client, monkeypatch):
    """It used to stamp the quote's currency on a holding that had none. No
    holding can have none now, and the one it has is what the reader stated:
    a refresh that disagrees updates the price and leaves the currency alone.
    On a row with units the listing's currency values it anyway, and the
    disagreement reaches the reader as `currency_note` — pointed out, not
    corrected behind their back."""
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    hid = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Walmart", "asset_class": "equity", "symbol": "WMT",
              "quantity": 10, "unit_price": 40, "currency": "EUR"},
    ).json()["id"]
    monkeypatch.setattr(
        prices,
        "get_quote",
        lambda s, base: {"symbol": s, "price": 50.0, "currency": "USD", "as_of": TODAY},
    )
    body = client.post(f"/api/holdings/{hid}/refresh-price").json()
    assert body["currency"] == "EUR" and body["unit_price"] == 50.0


def test_pence_are_not_pounds():
    """London quotes some funds in GBp (pence) and others in GBP (pounds) on the
    SAME exchange, and the codes differ only by one lowercase letter. Upper-
    casing before conversion turned 3361 pence into 3361 pounds: a position
    worth ~39 EUR valued at ~3870, a hundredfold error that looks entirely
    plausible on screen."""
    assert fx._in_major_units(3361.0, "GBp") == (33.61, "GBP")
    assert fx._in_major_units(3361.0, "GBX") == (33.61, "GBP")
    assert fx._in_major_units(1000.0, "ZAc") == (10.0, "ZAR")


def test_a_sloppy_lowercase_code_still_means_the_major_unit():
    """'gbp' is a careless spelling of pounds, not a claim about pence. Only the
    exact 'GBp' carries that meaning."""
    assert fx._in_major_units(106.85, "GBP") == (106.85, "GBP")
    assert fx._in_major_units(106.85, "gbp") == (106.85, "GBP")
    assert fx._in_major_units(100.0, "usd") == (100.0, "USD")
# --- A situation is a money total, and money totals are converted -----------


def test_a_situation_is_worth_what_its_holdings_convert_to(client, monkeypatch):
    """[M] The situations list and the account's own total are the same money.

    The specimen: 20 units of a Turkish listing at 4.47, recorded as 89.40 TRY
    inside one situation. The list of situations put a euro sign on that 89.40
    and printed it fifteen pixels above the account's invested total, which had
    gone through the projection and read 2. A factor of the exchange rate,
    twice on one screen, and the app said nothing.

    The cause was structural, not arithmetic: the sum lived on `Snapshot.value`,
    a model property, and a property has no session, so it could not reach the
    `fx.Converter` that is the only correct way to add two currencies. It is
    computed by the router now."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Turkish listing", "asset_class": "equity",
              "quantity": 20, "unit_price": 4.47, "currency": "TRY"},
    )
    _patch_rates(monkeypatch, {"2026-08-20": {"TRY": 44.7}})

    # 89.40 TRY / 44.7 = 2.00 EUR. (20 x 4.47 is 89.39999999999999 in binary
    # floating point, in the reader's database exactly as here.)
    one = client.get(f"/api/snapshots/{sid}").json()["value_base"]
    listed = client.get(f"/api/institutions/{iid}/snapshots").json()
    portfolio = client.get("/api/dashboard/portfolio").json()["total_book"]
    assert abs(one - 2.0) < 1e-9
    assert [s["value_base"] for s in listed] == [one]
    # The two figures that sat fifteen pixels apart and differed by the rate.
    assert abs(portfolio - one) < 1e-9


def test_a_holding_carries_both_what_was_typed_and_what_it_is_worth(client, monkeypatch):
    """[M] Two figures, two jobs, and the page needs both.

    `value` is what the reader typed, in `currency`, and the edit form has to
    put exactly that back in the box. `value_base` is the one that may be added
    to another row or shown with a euro sign. The Wealth page had only the
    first and used it for all three: the row's figure, the bucket's subtotal
    and the situation's total were sums of whatever each row happened to be
    denominated in."""
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    usd = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "US stock", "asset_class": "equity", "value": 125,
              "currency": "USD"},
    ).json()
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Bond fund", "asset_class": "bond", "value": 50, "currency": "EUR"},
    )
    _patch_rates(monkeypatch)

    # The typed figure is untouched; the converted one sits beside it.
    assert usd["value"] == 125 and usd["currency"] == "USD"
    fetched = client.get(f"/api/holdings/{usd['id']}").json()
    assert fetched["value"] == 125 and fetched["value_base"] == 100.0

    rows = client.get(f"/api/snapshots/{sid}/holdings").json()
    assert sorted(r["value_base"] for r in rows) == [50.0, 100.0]
    # What the page now totals, and what the situation says it is worth.
    assert sum(r["value_base"] for r in rows) == 150.0
    assert client.get(f"/api/snapshots/{sid}").json()["value_base"] == 150.0


def test_a_quantity_row_is_valued_by_its_listing_not_by_the_typed_currency(
    client, monkeypatch
):
    """[M] The rule this fix had to reuse rather than re-derive.

    A share class labelled USD can be quoted in EUR in Milan, and a value
    entered as units x that price is a EUR amount whatever the currency field
    says. Dividing it by the exchange rate is what once showed a 17% gain that
    never happened. The situation's total goes through `holding_book_in_base` for
    exactly this reason, so it reads the listing the projection reads, from the
    same price cache, and the two cannot disagree."""
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    hid = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "MSCI World", "asset_class": "fund_etf",
              "symbol": "MVOL.MI", "quantity": 10, "unit_price": 20,
              "currency": "USD"},
    ).json()["id"]
    _patch_rates(monkeypatch)
    # Before anyone has priced the ticker there is no cached listing, so both
    # readings fall back to the typed USD — TOGETHER, which is the invariant.
    assert client.get(f"/api/holdings/{hid}").json()["value_base"] == 160.0
    assert client.get("/api/dashboard/portfolio").json()["total_book"] == 160.0

    # The listing speaks: Milan quotes it in EUR, whatever the row was labelled.
    # The price cache is what carries that, and the live portfolio fetch fills
    # it — the same route the projection reads it back by.
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 20.0, "as_of": TODAY} for s in syms},
    )
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    assert client.get("/api/dashboard/portfolio?live=true").json()["total_book"] == 200.0

    # 200, not 160: the typed USD is overruled and nothing is divided by 1.25.
    assert client.get(f"/api/holdings/{hid}").json()["value_base"] == 200.0
    assert client.get(f"/api/snapshots/{sid}").json()["value_base"] == 200.0


def test_a_missing_rate_passes_the_raw_amount_through_rather_than_dropping_it(
    client, monkeypatch
):
    """[M] The rule `amount_in_base` was built on, inherited whole.

    With no rate for a currency the raw amount passes through, deliberately:
    a visible near-miss beats a dropped position. So a situation's total can
    still contain an unconverted row, and what says so is `fx_as_of` on the
    portfolio — null when nothing converted. The one thing that must never
    happen is the position vanishing from the total."""
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Tokyo listing", "asset_class": "equity",
              "value": 5000, "currency": "JPY"},
    )
    _patch_rates(monkeypatch)  # USD and GBP only: JPY has no rate

    assert client.get(f"/api/snapshots/{sid}").json()["value_base"] == 5000.0
    assert client.get(f"/api/dashboard/portfolio").json()["fx_as_of"] is None
