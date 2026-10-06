"""The MCP server: five tools an outside assistant can ask, and no way to write.

Two kinds of test live here, and they are different claims.

The first kind drives the server over the PROTOCOL, through the SDK's
in-memory transport — a real client, a real initialize handshake, real
`tools/list` and `tools/call` — because a server nobody connected to is not
finished, and a function called directly proves only that the function works.

The second kind pins the property the whole design rests on: this thing cannot
write. Not because the code is careful, but because the connection is opened
`mode=ro` and SQLite refuses. The test that matters most in this file is the
one that tries a write and is told no.

These build their rows through `client`, the app's own API, and then point the
server at the same file read-only — which is exactly the two-process shape the
server is for.
"""

from __future__ import annotations

import datetime
import sqlite3

import anyio
import pandas as pd
import pytest
from mcp.client import Client
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import catalogue, crud, fx, models, prices
from app.database import SessionLocal, engine
from app.mcp_server import build_server, read_only_url

TODAY = datetime.date.today().isoformat()


def _db_file() -> str:
    """The file the test suite's own engine is pointed at.

    Read off the engine rather than rebuilt from `conftest`'s private constant,
    so a test cannot end up reading a different file from the one `client` just
    wrote to and blame the server for the gap.
    """
    return engine.url.database


@pytest.fixture()
def server(client):
    """A server over the test database, opened read-only.

    Depends on `client` so the schema and the empty-table sweep have both
    happened: a `mode=ro` connection cannot create a file, and a missing one is
    an unhelpful error several layers from its cause.
    """
    return build_server(_db_file())


def _call(server, tool: str, **arguments):
    """One `tools/call` over the in-memory transport, returned as data.

    Synchronous on purpose. The suite has no async plugin, and adding one to
    run four lines of client code would be a dependency bought with somebody
    else's budget.
    """

    async def drive():
        async with Client(server, raise_exceptions=True) as c:
            return await c.call_tool(tool, arguments)

    result = anyio.run(drive)
    assert not result.is_error, f"{tool} came back as an error: {_text(result)}"
    return result.structured_content if result.structured_content is not None else result


def _one_position(client, **extra) -> tuple[int, int]:
    iid = client.post("/api/institutions", json={"name": "A broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "currency": "EUR", "asset_name": "A world tracker",
            "asset_class": "fund_etf",
            "symbol": "VWCE.MI",
            "quantity": 10,
            "unit_price": 100,
            **extra,
        },
    )
    return iid, sid


# --- It cannot write --------------------------------------------------------


def test_the_connection_itself_refuses_a_write(client):
    """The load-bearing test of this file.

    Every write in this app goes through a card the reader confirms, and an
    external client has no interface to show one — so the server must not be
    able to write at all. `read_only_hint` on the tools does not establish
    that: the protocol tells clients not to trust a server's own hints, which
    is precisely why the guarantee is put somewhere a hint cannot reach.

    Point the same factory at a writable URL and this passes the INSERT, which
    is what makes it a test of the URL rather than of SQLite.
    """
    from app.mcp_server import session_factory

    db = session_factory(_db_file())()
    try:
        assert db.execute(text("select count(*) from institutions")).scalar() == 0
        with pytest.raises(OperationalError, match="readonly database"):
            db.execute(text("insert into institutions (name) values ('X')"))
            db.commit()
    finally:
        db.close()


def test_the_read_only_url_names_the_file_and_the_mode():
    """Built from a PATH, never from `DATABASE_URL`.

    Honouring that variable the way the app does would let a writable
    connection in through a setting made for another purpose, and the property
    it would cost is the only one this server has.
    """
    url = read_only_url("some/where/data.db")
    assert url.startswith("sqlite:///file:") and "mode=ro" in url and "uri=true" in url


def test_a_rate_cache_a_week_old_does_not_stop_a_read(client, monkeypatch):
    """The bug a read-only connection introduces, and the reason `fx` asks.

    `rates_on` refreshes anything older than 24 hours and COMMITS the result,
    so on a connection SQLite will not write, the financial picture raised
    `OperationalError` instead of answering. Measured on a copy of the reader's
    own database before this existed: the cache was two days old and both
    `build_context` and `positions.project` died on it.

    Take the `read_only` branch out of `app/fx.py` and this test fails with
    that same error, which is what makes it a test and not a description.
    """
    stale = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    db = SessionLocal()
    db.add(models.FxRate(base="EUR", currency="USD", rate=1.1, as_of="2026-09-01", fetched_at=stale))
    db.commit()
    db.close()
    # A holding in a currency that is not the base one, because the converter
    # is LAZY: an all-EUR portfolio never asks for a rate, and this test passed
    # with the guard removed until something needed converting.
    _one_position(client, currency="USD")

    reached = []
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: reached.append(1))

    picture = _call(build_server(_db_file()), "get_financial_picture")
    assert "# User financial situation" in _text(picture)
    # Not merely "it did not crash": a read-only reader must not go to the ECB
    # either. Fetching and then failing to store would spend a network call per
    # tool call, for ever, to learn the same thing each time.
    assert reached == [], "a session that cannot write still went to the network"


def test_a_writer_mid_transaction_does_not_block_the_reader(client):
    """The app may be running while this is, so 'SQLite holds concurrent
    readers' had to be verified rather than repeated.

    An open write transaction holds a RESERVED lock, and a reader passes
    straight through it. The one window that does block is the commit flush,
    which takes an EXCLUSIVE lock for milliseconds — measured at 0.5s held
    artificially, a reader with no busy timeout failed in 19 ms and the same
    reader with the 5-second one this server sets returned correct rows after
    506 ms. That window is not reproduced here because holding it open needs a
    second process and a sleep, which buys a flaky test rather than a fact.
    """
    _one_position(client)
    writer = sqlite3.connect(_db_file(), timeout=5, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("update institutions set name = 'Renamed' where 1=1")
        body = _call(build_server(_db_file()), "get_positions")
        assert body["positions"], "the reader saw nothing while a write was open"
        # The uncommitted rename is invisible, which is the other half of the
        # guarantee: a reader is not blocked AND is not shown a half-written
        # state.
        assert body["positions"][0]["institution"] == "A broker"
        writer.execute("ROLLBACK")
    finally:
        writer.close()


# --- It speaks the protocol -------------------------------------------------


def _text(result) -> str:
    """The text of a tool result, whatever block shape it came back in."""
    return "\n".join(getattr(c, "text", "") for c in result.content)


def test_a_client_sees_five_tools_and_every_one_says_it_only_reads(server):
    """The handshake and the listing, over a real transport.

    The names are pinned because they are an interface: a caller's saved
    prompt refers to them, and renaming one is not a refactor.
    """

    async def drive():
        async with Client(server, raise_exceptions=True) as c:
            return await c.list_tools()

    tools = anyio.run(drive).tools
    assert sorted(t.name for t in tools) == [
        "get_financial_picture",
        "get_last_analysis",
        "get_positions",
        "lookup_symbol",
        "search_catalogue",
    ]
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    # The descriptions are the ONLY documentation an outside model gets, so an
    # empty one is a tool nobody can use correctly.
    assert all(t.description and len(t.description) > 200 for t in tools)


def test_every_tool_answers_over_the_protocol(server, client, monkeypatch):
    """Each of the five, called the way Claude Desktop would call it.

    One test rather than five because what it establishes is the same fact
    about each: the round trip completes and the result is not an error. What
    each one SAYS is pinned separately below.
    """
    _one_position(client)
    monkeypatch.setattr(prices, "_fetch_lookup", lambda q, n: [])
    for tool, args in [
        ("get_financial_picture", {}),
        ("get_positions", {}),
        ("search_catalogue", {"query": "vanguard"}),
        ("lookup_symbol", {"query": "VWCE"}),
        ("get_last_analysis", {}),
    ]:
        # `_call` asserts the round trip did not come back as an error, which
        # is the whole claim here.
        _call(server, tool, **args)


def test_the_picture_is_the_app_s_own_context_and_not_a_second_rendering(server, client):
    """Byte for byte what `build_context` produces.

    A preamble added only out here would be a second rendering of the same
    document, and the app's copy is the one under test — so the one nobody
    notices going stale would be this one. Framing for an outside caller goes
    in the server's `instructions`, which is sent once and is not a number.
    """
    _one_position(client)
    db = SessionLocal()
    try:
        from app import advisor

        expected = advisor.build_context(db)
    finally:
        db.close()
    assert _text(_call(server, "get_financial_picture")) == expected


def test_the_picture_does_not_cross_the_wire_twice(server, client):
    """A document has nothing to destructure, so it is sent once.

    The SDK infers structured output from the return annotation, and a `-> str`
    tool is helpfully given BOTH a text block and a `{"result": ...}` copy of
    the same characters. Measured on the reader's own portfolio: 1,361
    characters of document became 2,797 across the wire. Every assistant that
    ever calls this pays for the second copy, and no caller can use it.
    """
    _one_position(client)

    async def drive():
        async with Client(server, raise_exceptions=True) as c:
            return await c.call_tool("get_financial_picture", {})

    result = anyio.run(drive)
    assert "# User financial situation" in _text(result)
    assert result.structured_content is None, "the document was sent a second time"


# --- What each tool says ----------------------------------------------------


def test_a_position_keeps_what_it_cost_apart_from_what_it_is_worth(server, client):
    """The distinction that makes a P/L honest.

    A holding recorded from a photograph has no price anybody paid, so
    `cost_known` is false and `book_value` is the photograph's own figure.
    Subtracting one from the other and calling it a gain is the error the flag
    exists to prevent, and an outside model cannot know that unless the flag
    travels with the row.
    """
    _one_position(client)
    body = _call(server, "get_positions")
    (row,) = body["positions"]
    assert row["institution"] == "A broker" and row["symbol"] == "VWCE.MI"
    assert row["cost_known"] is False
    assert row["book_value"] == 1000.0 and row["observed_value"] == 1000.0
    # Nothing priced it — the cache is empty — so the row is wholly as old as
    # its photograph, and `current_value` falls back to the observation.
    assert row["market_value"] is None and row["current_value"] == 1000.0
    assert row["observed_on"] == TODAY
    assert "cost_known" in body["reading"] and "observed_on" in body["reading"]


def test_positions_report_the_date_of_the_rates_they_were_converted_at(server, client):
    """Provenance travels with the number, including out here.

    `positions.project` reports the rate date only to a converter its caller
    owns; one that makes its own has nowhere to put it. An assistant told a
    figure in EUR and not told when the rate was struck cannot say how old the
    conversion is.
    """
    db = SessionLocal()
    db.add(models.FxRate(base="EUR", currency="USD", rate=1.1, as_of="2026-09-04", fetched_at=models._utcnow_iso()))
    db.commit()
    db.close()
    _one_position(client, currency="USD")

    body = _call(server, "get_positions")
    assert body["base_currency"] == "EUR"
    assert body["rates_as_of"] == "2026-09-04"


def test_a_fund_arrives_with_its_twin_and_says_how_it_matched(server, client, monkeypatch):
    """The two share classes travel together, out here as on the screen.

    They carry the same name and differ only in what they do with dividends, so
    an assistant shown one alone would recommend it without ever revealing
    there was a choice. `coverage` comes with them because a loosened match is
    a weaker claim about what was asked, and an assistant that cannot tell the
    two apart will present a guess as a find.
    """
    catalogue_rows = pd.DataFrame(
        [
            {
                "name": "Acme World UCITS ETF (Acc)", "ticker": "AWA",
                "dividends": "Accumulating", "ter": 0.12, "size": 210,
                "replication": "Full replication", "domicile_country": "Ireland",
                "currency": "EUR", "number_of_holdings": 21, "hedged": False,
            },
            {
                "name": "Acme World UCITS ETF (Dist)", "ticker": "AWD",
                "dividends": "Distributing", "ter": 0.12, "size": 415,
                "replication": "Full replication", "domicile_country": "Ireland",
                "currency": "EUR", "number_of_holdings": 21, "hedged": False,
            },
        ],
        index=pd.Index(["IE00ACME0001", "IE00ACME0002"], name="isin"),
    )
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: catalogue_rows)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200

    body = _call(server, "search_catalogue", query="Acme World")
    assert body["coverage"] == "all"
    (family,) = body["families"]
    assert sorted(m["distribution_policy"] for m in family["members"]) == ["acc", "dist"]
    # The source is described apart from the match, so "an old catalogue" and
    # "a weak match" are never read as the same doubt.
    assert body["catalogue"]["instruments"] == 2 and body["catalogue"]["source"] == "justetf"


def _drop_the_search_index() -> None:
    """Take the FTS5 index away, whoever built it.

    Explicit because it has to be: the index is a virtual table, so it is not
    in `Base.metadata` and `conftest`'s sweep empties it rather than dropping
    it. It therefore SURVIVES the whole session once any test has searched the
    catalogue, and a test that assumed a fresh database would pass alone and
    fail behind `test_catalogue.py`.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS instruments_fts")


def test_a_machine_with_no_catalogue_says_so_instead_of_failing(server):
    """The absence is reported, and reported as an absence of the CATALOGUE.

    `catalogue.search` builds its index on demand, and a read-only connection
    cannot build anything — so this used to come back as a SQLite error about a
    readonly database, which tells an outside assistant nothing it can act on.
    Worse, the plausible thing for it to say next is "no such fund exists",
    which is the trap `docs/how-aurelio-reasons.md` names: an absence presented as a denial.
    """
    _drop_the_search_index()
    body = _call(server, "search_catalogue", query="anything at all")
    assert body["families"] == [] and body["coverage"] == "none"
    assert "no fund registry" in body["reading"]
    assert "NOT evidence that no such fund exists" in body["reading"]


def test_a_registry_that_is_merely_unindexed_is_not_reported_as_empty(server, client):
    """Two reasons, two answers.

    A database holding 4,500 instruments whose index was never built needs the
    app opened once; one holding none needs a download. Collapsing them into a
    single 'nothing here' sends somebody to re-fetch a catalogue they already
    have, and quietly says their data is missing when it is not.
    """
    db = SessionLocal()
    try:
        db.add(models.Instrument(
            isin="IE00ACME0001", name="Acme World UCITS ETF (Acc)",
            family_key="acme world ucits etf", source="justetf",
            fetched_at=models._utcnow_iso(),
        ))
        db.commit()
    finally:
        db.close()
    _drop_the_search_index()

    body = _call(server, "search_catalogue", query="acme")
    assert "1 instruments" in body["reading"] and "index has not been built" in body["reading"]
    assert "Nothing is missing from the data" in body["reading"]


def test_an_empty_lookup_refuses_to_say_the_instrument_does_not_exist(server, monkeypatch):
    """'Nobody answered' and 'this does not exist' are different statements.

    `prices.lookup` returns [] for both, and inside the app that is right — the
    picker has a second lane and one going quiet must not take the other with
    it. Out here there is no second lane, and `docs/how-aurelio-reasons.md` lists presenting the
    first as the second among the bugs already paid for: it teaches somebody to
    correct a ticker that was right. The distinction cannot be recovered from
    this side, so it is declared.
    """
    monkeypatch.setattr(prices, "_fetch_lookup", lambda q, n: [])
    body = _call(server, "lookup_symbol", query="nothing at all")
    assert body["matches"] == []
    assert "either nothing matches" in body["reading"]
    assert "did not answer" in body["reading"]


def test_two_listings_of_one_company_are_not_two_prices_to_compare(server, monkeypatch):
    """The same instrument trades in several places under one name, and the
    exchange is what tells the rows apart rather than a duplicate to tidy away.

    The sharper half is the money. Yahoo's search returns a bare price and
    never says what currency it is in, so two rows for one company can read
    15% apart and be the same value at the exchange rate. Inside the app that
    is safe: the currency arrives from a real quote once a listing is chosen.
    An external assistant chooses nothing and will simply compare the numbers,
    so the warning has to travel in the payload.
    """
    monkeypatch.setattr(
        prices,
        "_fetch_lookup",
        # The real shape, keys and all: there is NO currency field, which is
        # the whole reason this test exists. A fake that invented one would
        # quietly assert the opposite of what the source does.
        lambda q, n: [
            {"symbol": "ACME", "name": "Acme Industries, Inc.",
             "quote_type": "EQUITY", "exchange": "NMS", "price": 50.00},
            {"symbol": "AC1.F", "name": "Acme Industries Inc.",
             "quote_type": "EQUITY", "exchange": "FRA", "price": 43.50},
        ],
    )
    body = _call(server, "lookup_symbol", query="acme industries")
    assert [m["exchange"] for m in body["matches"]] == ["NMS", "FRA"]
    assert all("currency" not in m for m in body["matches"])
    assert "one LISTING" in body["reading"]
    # 50.00 and 43.50 can be the SAME value in two currencies, and nothing in the
    # payload says so. An assistant not warned will report a 15% gap or pick
    # the cheaper listing, which is the error `prices._fetch_lookup` documents.
    assert "different money" in body["reading"]
    assert "do not compare" in body["reading"]


def test_an_analyzer_that_never_ran_is_an_absence_and_not_an_empty_verdict(server):
    """The same rule the financial picture follows about a missing date.

    A null verdict reads to a model as a conclusion that came back empty, and
    it would report 'the analysis found nothing'. Saying it has never run is a
    different fact and the true one.
    """
    body = _call(server, "get_last_analysis")
    assert body["run_id"] is None
    assert "never been run" in body["reading"]


def test_the_last_analysis_brings_the_verdict_whole_and_the_argument_as_a_spine(server, client):
    """The decision the backlog left open, made the way the app already made it
    for its own surfaces.

    The verdict is what was written to the reader, so it comes whole. What each
    role wrote is four more documents, and pulling them in to answer a question
    about the conclusion means paying for the chain's reasoning in order to
    read its answer. `challenge` is the confidant's own marker and not a count
    of the steps: the two disagree in both directions.
    """
    db = SessionLocal()
    try:
        crud.create_chain_run(
            db,
            verdict="Hold the course.",
            steps=[
                {"role": "analyst", "title": "Blind read", "model": "m1",
                 "output": "A long document nobody out here should pay for.",
                 "duration_ms": 4000, "cost": 0.01},
                {"role": "confidant", "title": "The challenge", "model": "m2",
                 "output": "Some argument.\nVERDICT: CONTESTED", "duration_ms": 2000, "cost": 0.01},
            ],
        )
    finally:
        db.close()

    body = _call(server, "get_last_analysis")
    assert body["verdict"] == "Hold the course."
    assert body["challenge"] == "contested"
    assert [s["role"] for s in body["steps"]] == ["analyst", "confidant"]
    assert [s["seconds"] for s in body["steps"]] == [4.0, 2.0]
    # The spine, not the text: no step carries what its model actually wrote.
    assert all("output" not in s for s in body["steps"])
    assert "A long document" not in str(body)
