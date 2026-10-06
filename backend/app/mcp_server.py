"""The portfolio, speakable from outside the app: a read-only MCP server.

Five tools over stdio, so Claude Desktop — or any assistant that speaks MCP —
can be asked about this wealth without the app being the one holding the
conversation. It is a wrapper and nothing else: every number it returns is
computed by the same function the app's own screens call, so there is no
second implementation of anything here to drift from the first.

READ-ONLY, AND NOT AS A PROMISE. The connection is opened `mode=ro`, so it is
SQLite that refuses a write, not this file's good intentions. That matters
because of a distinction the app defends everywhere else: every write goes
through a card the reader confirms, and an external client has no interface to
show one. A server that could write would have to invent consent, and the only
honest way not to invent it is to be unable to write at all. The `read_only`
flag on each session (see `app/database.py`) tells the one code path that
opportunistically refreshes a cache — the ECB rates — to serve what is stored
rather than raise.

WHY IT LIVES IN `app/`. It imports six modules from this package and adds no
concepts of its own, so a sibling package would need its own project metadata
to buy nothing, and a loose script would be reachable only by path — which the
test would then have to perform surgery on. Here `uv run python -m
app.mcp_server` works from `backend/`, and `tests/` imports it exactly the way
it imports everything else.

A SEPARATE PROCESS from the app, which may be running at the same time. That
is fine and was measured rather than assumed (`tests/test_mcp_server.py`):
SQLite in this database's rollback-journal mode lets a reader through while a
writer holds an open transaction, and blocks it only for the milliseconds of
the commit flush — which the busy timeout below waits out instead of failing.

Run it:

    cd backend && uv run python -m app.mcp_server

`AURELIO_MCP_DB` points it at a different file, which is how the tests and any
probe run against a COPY instead of the reader's own database.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app import advisor, catalogue, chain, crud, fx, positions, prices
from app.database import DEFAULT_DB_PATH, READ_ONLY

SERVER_NAME = "aurelio"

# What the client is told once, so five descriptions do not each repeat it.
# Everything here changes how a number is READ; nothing here is a fact about
# how the app is built, because a caller cannot act on those and pays for them
# on every listing.
INSTRUCTIONS = """\
Aurelio is one person's wealth, kept locally. These tools read it and can
never change it.

Three things decide whether you read the numbers correctly.

Totals are in the base currency of this database, and every answer names it:
the financial picture says it under its title, and structured results carry
`base_currency`. Anything recorded in another currency was converted at the
ECB reference rate, and the date of the rate used comes back with the figures
it produced; a figure a record states itself is given in its own currency.

Wealth is an anchor plus events, not a running balance. Each institution has
dated situations — a photograph of what was held there — and today's figure is
the most recent photograph plus every ledger entry dated strictly after it. So
a total can differ from what a bank's app shows today without either being
wrong: ask when the photograph was taken.

Nothing here is live market data. Positions are priced from a cache the app
fills; a quote may be a day old, and some rows cannot be priced at all and say
so. `lookup_symbol` is the one tool that reaches the network.
"""

# Both the truthful annotation and the fact that the connection is `mode=ro`.
# The annotation alone would be worth little — the protocol says clients must
# not trust a server's hints — which is exactly why the guarantee is in the
# connection and this only describes it.
READS = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)


# --- The database, opened so that it cannot be written --------------------


def read_only_url(db_path: str | os.PathLike[str] | None = None) -> str:
    """A SQLAlchemy URL for a SQLite file that SQLite itself will not write.

    Deliberately a PATH and not a URL: honouring `DATABASE_URL` the way the app
    does would let a writable connection in through a variable somebody set for
    another purpose, and the one property this server may not lose is the one
    that would go first.
    """
    path = Path(db_path or os.getenv("AURELIO_MCP_DB") or DEFAULT_DB_PATH).resolve()
    return f"sqlite:///file:{path.as_posix()}?mode=ro&uri=true"


def session_factory(db_path: str | os.PathLike[str] | None = None) -> sessionmaker[Session]:
    """A factory for read-only sessions on `db_path`.

    Its own engine, because this is a different process from the app with a
    different contract, and because `app.database.engine` is writable.

    `timeout` is what makes "SQLite holds concurrent readers" true rather than
    nearly true. Measured on a copy of the reader's database: while the app
    holds an open write transaction a read still returns in about a
    millisecond, but during the commit flush a reader with no busy timeout
    fails in ~19 ms with "database is locked", and the same reader with a
    5-second one simply waits the flush out. It is sqlite3's own default and is
    passed explicitly because it is load-bearing, not incidental.
    """
    engine = create_engine(
        read_only_url(db_path),
        connect_args={"check_same_thread": False, "timeout": 5.0},
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _why_the_catalogue_cannot_be_searched(db: Session) -> str | None:
    """None when the search will run; otherwise why it will not, in words.

    `catalogue.search` builds its FTS5 index on demand — a database that
    predates the feature heals itself on first use — and a connection that
    cannot write cannot heal anything. Left alone, that turns "you have never
    downloaded the catalogue" into a tool call that fails with a SQLite error,
    which tells an outside assistant nothing it can act on and invites it to
    retry.

    The two reasons are separated because they have different answers: one
    needs a download, the other needs the app opened once. Reporting them as
    the same absence would send somebody to re-download 4,500 rows they already
    have.
    """
    indexed = db.execute(
        text("SELECT count(*) FROM sqlite_master WHERE name = 'instruments_fts'")
    ).scalar()
    if indexed:
        return None
    rows = db.execute(text("SELECT count(*) FROM instruments")).scalar() or 0
    if rows:
        return (
            f"The fund registry holds {rows} instruments but its search index "
            "has not been built yet, and this connection is read-only so it "
            "cannot build one. Opening Aurelio and searching once will do it. "
            "Nothing is missing from the data."
        )
    return (
        "There is no fund registry on this machine yet — it is downloaded from "
        "inside Aurelio, and until then this tool can find nothing. This is an "
        "absence of the catalogue, NOT evidence that no such fund exists."
    )


@contextmanager
def _reading(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """One session per tool call, marked as unable to write.

    Per call rather than one for the server's life: a long-lived SQLite session
    holds a read transaction open and would keep showing the snapshot it began
    with, so an assistant asked the same question twice after the reader
    recorded something would get the stale answer the second time.
    """
    db = sessions()
    db.info[READ_ONLY] = True
    try:
        yield db
    finally:
        db.close()


# --- The tools -------------------------------------------------------------


def build_server(db_path: str | os.PathLike[str] | None = None) -> MCPServer:
    """The server, with its five tools bound to a read-only view of `db_path`.

    A function and not a module-level singleton, so a test can point one at a
    copy without an import-time decision having already picked the real file.
    """
    sessions = session_factory(db_path)
    server = MCPServer(
        name=SERVER_NAME,
        title="Aurelio — this portfolio, read-only",
        instructions=INSTRUCTIONS,
        version="1",
    )

    @server.tool(
        name="get_financial_picture",
        annotations=READS,
        # A string return would otherwise be sent TWICE — once as a text block
        # and once wrapped as {"result": ...} in the structured field. Measured
        # on the reader's own portfolio: 1,361 characters of document became
        # 2,797 across the wire. There is nothing to destructure in a document,
        # so the second copy is pure cost.
        structured_output=False,
        description=(
            "The whole financial situation as one document: net worth and what "
            "it is made of, allocation, monthly income and expenses, every "
            "investment position, the recent ledger, cash per institution, "
            "real assets, debts, goals and the answers this person gave about "
            "their life. Start here for almost any question — it is one call, "
            "and the sections answer each other ('can I afford this' is also a "
            "question about the expenses). Reach for the other tools only when "
            "the question is about a specific position's detail, an instrument "
            "that is not owned, or what the analyzer last concluded."
        ),
    )
    def get_financial_picture() -> str:
        """The app's own context document, byte for byte.

        NOT reshaped into JSON, and nothing prepended. It is already written
        for a model to read — headings, one fact per line, absences stated as
        absences rather than as nulls — so an outside assistant wants the same
        text the inside one gets. The stronger reason is that a second
        rendering would be a second thing to keep true: the app's copy is the
        one under test, and a preamble only this server adds would be the one
        nobody notices going stale. What an external caller needs on top of it
        is framing, and framing belongs in `INSTRUCTIONS`.
        """
        with _reading(sessions) as db:
            return advisor.build_context(db)

    @server.tool(
        name="get_positions",
        annotations=READS,
        description=(
            "Every investment position held today, one row each, with the "
            "figures kept apart instead of blended: what it cost, what its "
            "last photograph said it was worth, and what the market says now. "
            "Two flags decide whether a number means what it looks like. "
            "`market_value` is null when nothing can price the row — no "
            "ticker, no quantity or no quote — and then `current_value` falls "
            "back to the last observed value and the WHOLE row is as old as "
            "`observed_on`; where it is present, only the quantity is that "
            "old and the value is today's. `cost_known` is false when the "
            "cost is a photograph's value rather than a price anybody paid, "
            "and a profit computed from it is invented. Use for questions "
            "about a specific holding, a gain, or what is stale."
        ),
    )
    def get_positions() -> dict[str, Any]:
        """The projection, as a table, with institution ids resolved to names.

        Structured and not prose, because these are the same attributes across
        many rows and a question like "which of these has not been confirmed
        this year" is a comparison — prose would make the caller parse its way
        back to the fields it just lost.

        The converter is passed in rather than left to the projection so that
        `used_as_of` survives: a conversion carries the date of the rate that
        made it, and a projection that builds its own converter has nowhere to
        report that date to.
        """
        with _reading(sessions) as db:
            conv = fx.Converter(db)
            rows = positions.project(db, conv)
            names = {i.id: i.name for i in crud.get_institutions(db)}
            return {
                "base_currency": conv.base,
                "rates_as_of": conv.used_as_of,
                "positions": [
                    {
                        "institution": names.get(p.institution_id),
                        "asset_name": p.asset_name,
                        "symbol": p.symbol,
                        "isin": p.isin,
                        "asset_class": p.asset_class,
                        "distribution_policy": p.distribution_policy,
                        "quantity": p.quantity,
                        "book_value": p.book_value,
                        "cost_known": p.cost_known,
                        "cost_estimated": p.cost_estimated,
                        "observed_value": p.observed_value,
                        "market_value": p.market_value,
                        "current_value": p.current_value,
                        "realized_pl": p.realized_pl,
                        "dividends": p.dividends,
                        "observed_on": p.observed_on,
                        "closed_on": p.closed_on,
                        "currency_note": p.currency_note,
                    }
                    for p in rows
                ],
                "reading": (
                    "`rates_as_of` is the date of the exchange rates these "
                    "figures were converted at, and is null when nothing "
                    "needed converting. A position whose `market_value` is "
                    "null could not be priced, so every part of it is as of "
                    "`observed_on` and only the reader can refresh it. Where "
                    "`cost_known` is false, `book_value` is what a photograph "
                    "said the row was worth and not a price paid: do not "
                    "subtract it from a value and call the difference a gain."
                ),
            }

    @server.tool(
        name="search_catalogue",
        annotations=READS,
        description=(
            "Search the LOCAL registry of UCITS funds and ETFs by name: ISIN, "
            "ongoing charge, domicile, replication, size, and whether the "
            "share class accumulates or distributes. Instant, and it knows "
            "nothing about prices — this is identity, not quotation, so it "
            "cannot tell you what anything is worth or on which exchange to "
            "buy it. Results come back grouped into families so a fund's "
            "accumulating and distributing twins always arrive together: they "
            "share a name and differ only in what they do with dividends, and "
            "showing one alone invites choosing it without knowing there was "
            "a choice. Use it to compare funds or to find an ISIN. For a "
            "quotable symbol use `lookup_symbol` instead."
        ),
    )
    def search_catalogue(query: str, limit: int = 8) -> dict[str, Any]:
        """The catalogue lane, kept separate from the price lane on purpose.

        Merging the two would make this one — local, instant — wait for a
        network call every time, which is the argument `docs/how-aurelio-reasons.md` makes about
        the instrument picker and it does not stop being true out here.

        `status()` comes back reshaped into one `catalogue` object rather than
        three loose keys beside the families, because it describes the source
        and not the match, and a caller weighing a partial match needs to be
        able to tell those apart at a glance.
        """
        with _reading(sessions) as db:
            unsearchable = _why_the_catalogue_cannot_be_searched(db)
            if unsearchable:
                return {"families": [], "coverage": "none", "reading": unsearchable}
            found = catalogue.search(db, query, limit=limit)
            return {
                "families": found["families"],
                "coverage": found["coverage"],
                "catalogue": {
                    "instruments": found["rows"],
                    "fetched_at": found["fetched_at"],
                    "source": found["source"],
                },
                "reading": (
                    "`coverage` says how the match was made. 'all' means every "
                    "word was found; 'partial' means the search had to loosen "
                    "to find anything, so the results are a weaker claim about "
                    "what was asked and should be offered as such; 'none' "
                    "means nothing matched. Each family lists every share "
                    "class of the same fund, which is why two rows can look "
                    "like duplicates and are not."
                ),
            }

    @server.tool(
        name="lookup_symbol",
        annotations=READS,
        description=(
            "Find a QUOTABLE symbol — shares, ETFs, crypto, futures — with its "
            "exchange and last price. The only tool here that reaches the "
            "network, and the only one that can say what something trades as: "
            "the same instrument has a different symbol on every exchange it "
            "is listed on, so the exchange is part of the answer and not "
            "decoration. NEVER COMPARE TWO PRICES FROM THIS TOOL. The source "
            "does not say what currency each one is in, and two listings of "
            "the same company routinely differ by the exchange rate alone — "
            "quote a price only next to its exchange, and never call one "
            "cheaper than another. It knows no ISINs; for identity, ongoing "
            "charges or accumulating-versus-distributing use "
            "`search_catalogue`. An empty result is ambiguous and says so."
        ),
    )
    def lookup_symbol(query: str, count: int = 8) -> dict[str, Any]:
        """The price lane. Its empty answer is reported as ambiguous.

        `prices.lookup` returns [] both when nothing matched and when the
        source did not answer, and inside the app that is right: the picker has
        a second lane, and one going quiet must never take the other down with
        it. Out here there is no second lane, and `docs/how-aurelio-reasons.md` names the
        resulting confusion as a trap already paid for — "nobody answered" and
        "this instrument does not exist" are different statements, and
        presenting the first as the second teaches somebody to correct a ticker
        that was right. The distinction cannot be recovered from this side, so
        it is declared instead of hidden.

        The only tool that opens no session: this question is not about the
        reader's wealth at all, and a session held open across a network call
        would be a read transaction on their database for the length of it.
        """
        matches = prices.lookup(query, count)
        return {
            "matches": matches,
            "reading": (
                "Each match is one LISTING, so the same instrument appears "
                "several times under different exchanges. No price here says "
                "what currency it is in, and across two rows they are usually "
                "different money — the source does not report it. Quote a "
                "price with its exchange, and do not compare, convert or rank "
                "them. Aurelio learns the currency from an actual quote, "
                "after a listing has been chosen."
                if matches
                else "No result, and this tool cannot tell you which kind: "
                "either nothing matches that query, or the price source did "
                "not answer. Do not report it as 'that instrument does not "
                "exist'."
            ),
        }

    @server.tool(
        name="get_last_analysis",
        annotations=READS,
        description=(
            "What the in-app analyzer concluded the last time it ran: its "
            "verdict in full, plus the spine of the argument behind it — which "
            "roles spoke, in what order, and whether the adversarial one "
            "actually argued. The analyzer is several models in sequence: one "
            "judges the portfolio without being told whose it is, someone who "
            "knows the person challenges that without seeing a figure, and a "
            "revision round happens only where the challenge was contested. "
            "Returns nothing but says so when it has never been run. It cannot "
            "start a run — that costs money and needs the person's consent in "
            "the app."
        ),
    )
    def get_last_analysis() -> dict[str, Any]:
        """The verdict in full; the steps as a spine, without their text.

        The decision the backlog left open, and the app has already made it
        twice for its own surfaces (`app/tools.py`, `schemas.ChainRunSummary`)
        for a reason that holds harder out here: what each role wrote is four
        more documents, and pulling all of them in to answer a question about
        the conclusion means paying for the chain's reasoning to read its
        answer. The verdict is the thing that was written to the reader, so it
        comes whole.

        `challenge` is the confidant's own marker rather than a count of the
        steps. The two disagree in both directions — a confidant that contests
        on the last round allowed buys no further revision and still contested,
        one that says nothing at all buys one and declared nothing — and
        counting revisions would report the first as agreement and the second
        as argument.

        An earlier design named `AdvisorReport` for this. That class no
        longer exists; `ChainRun` replaced it.
        """
        with _reading(sessions) as db:
            run = crud.get_latest_chain_run(db)
            if run is None:
                return {
                    "run_id": None,
                    "reading": (
                        "The analyzer has never been run on this portfolio, so "
                        "there is no verdict. This is an absence, not an empty "
                        "verdict — do not read it as 'the analysis found "
                        "nothing'."
                    ),
                }
            return {
                "run_id": run.id,
                "finished": run.created_at,
                "verdict": run.verdict,
                "challenge": (chain.challenge_of(run) or "unstated").lower(),
                "steps": [
                    {
                        "step_no": s.step_no,
                        "role": s.role,
                        "title": s.title,
                        "model": s.model,
                        "seconds": None if s.duration_ms is None else round(s.duration_ms / 1000, 1),
                    }
                    for s in run.steps
                ],
                "reading": (
                    "`verdict` is what was written to the reader and is the "
                    "answer. The steps are listed without their text, which is "
                    "four more documents and lives in the app. `challenge` is "
                    "what the adversarial role declared: 'contested' means it "
                    "argued, 'fits' that it agreed, and 'unstated' that it "
                    "said neither — which is a third answer and not a quiet "
                    "'fits'."
                ),
            }

    return server


def main() -> None:
    """Serve on stdio — the transport Claude Desktop speaks."""
    build_server().run("stdio")


if __name__ == "__main__":
    main()
