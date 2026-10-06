"""Shared pytest fixtures.

The app engine reads DATABASE_URL at import time, so we point it to a
throwaway SQLite file BEFORE importing the app.

Two things in here decide what a suite run MEANS, so they live together:
isolation between tests (the schema is built once, the rows go away between
tests) and the network boundary (every outside call is refused, so the same
run offline says the same thing as online).
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import sqlite3
import tempfile
import threading
from contextlib import closing

# One file per pytest process. The path used to be fixed, so two runs at once
# — an editor's watcher and a terminal, say — shared a database and dropped
# each other's tables mid-test. The failures that produces ("no such table")
# blame the code under test for something the other run did, which is the one
# thing a test suite must never do.
_TMP_DB = pathlib.Path(tempfile.gettempdir()) / f"aurelio_pytest_{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
# Tests build the schema straight from the models, skipping Alembic.
os.environ["AURELIO_SKIP_MIGRATIONS"] = "1"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app import advisor, catalogue, composition, database, fx, issuers, prices  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


# --- Isolation --------------------------------------------------------------


@event.listens_for(engine, "connect")
def _durability_is_worthless_here(dbapi_connection, connection_record) -> None:
    """Stop fsyncing a database we are about to throw away.

    SQLite flushes to disk on every commit, and a test suite commits
    constantly. Losing this file to a crash costs nothing — it is rebuilt from
    the models on the next run — so the guarantee we are paying for is one we
    do not want. Only ever applied to the temp file above, never to the app's
    own database, which is not this engine's business to be fast about.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA journal_mode=MEMORY")
    cursor.close()


@pytest.fixture(scope="session")
def _schema():
    """Build the tables once for the whole session.

    They used to be dropped and recreated for every single test: 24 tables of
    DDL, 178 times over, each statement fsynced. That fixture cost ~47s of a
    73s run — three times what the tests themselves took, which is the wrong
    way round for the thing you are supposed to run after every edit.
    Isolation never needed NEW tables, only empty ones.

    It still starts from a drop, which clears anything a crashed run of THIS
    schema left behind if the process id came round again — not anything else:
    drop_all only knows the tables in Base.metadata. It takes the file away
    afterwards rather than leaving one per process id in the temp directory.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    try:
        _TMP_DB.unlink(missing_ok=True)
    except OSError:
        # Windows will not delete a file something still holds open. A leftover
        # scratch file in the temp directory is not worth turning a green run
        # red over, and the next run makes its own.
        pass


def _empty_every_table() -> None:
    """Take the rows out of the schema and leave the schema alone.

    Children first — the reverse of SQLAlchemy's dependency order — so the
    foreign keys the app actually runs under stay enforced during the sweep
    instead of being switched off for it. SQLite has no AUTOINCREMENT here, so
    the id counters fall back to 1 exactly as a fresh table would.
    """
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        # instruments_fts is an FTS5 virtual table built on demand by
        # catalogue._ensure_fts, not by SQLAlchemy, so it is not in
        # Base.metadata and the loop above cannot see it. Nothing reads the
        # index without joining `instruments`, which IS swept, so leaving it
        # is not a wrong answer today — it is the invariant that stops the
        # first read that does not join. OperationalError: no test has
        # searched yet, so the table does not exist.
        try:
            conn.exec_driver_sql("DELETE FROM instruments_fts")
        except OperationalError:
            pass


@pytest.fixture(autouse=True)
def empty_database(_schema):
    """Every test starts with the schema present and no rows in it.

    Autouse rather than something `client` does for itself: seven test files
    open a `SessionLocal()` of their own, and today they are isolated only by
    the accident that each of them also happens to ask for `client`. The first
    one that does not would read whatever the previous test wrote, and read it
    as its own. The sweep costs a third of a millisecond, so the tests that
    touch no database at all pay nothing for the guarantee.
    """
    _empty_every_table()


@pytest.fixture()
def client(empty_database):
    """A TestClient over the empty schema `empty_database` just left.

    It names that fixture rather than trusting autouse ordering: the app builds
    any missing table on startup, and a client that entered first would be
    serving a test rows the sweep had not taken out yet.
    """
    with TestClient(app) as c:
        yield c


# --- The network boundary ---------------------------------------------------

# Every module that talks to the outside world keeps its calls in a `_fetch_*`
# helper, precisely so a test can replace them. This is the list of those
# helpers, and it is complete on purpose: a boundary that is only mostly faked
# is not a boundary, and the assertions behind the gap quietly become a report
# on today's weather at Yahoo.
#
# `prices._fetch_recent_close` is deliberately NOT here any more: it stopped
# being a call and became a reading of `_fetch_close_window` — which day is the
# last one that HAS a close — so the refusal below still stands behind it,
# through the helper it composes, while the reading itself can be tested.
_NETWORK_BOUNDARY = {
    prices: (
        "_fetch_probe", "_fetch_close_window", "_fetch_name",
        "_fetch_recent_closes", "_fetch_currency", "_fetch_dividends",
        "_fetch_lookup", "_fetch_openfigi",
    ),
    composition: (
        "_justetf_catalogue", "_fetch_trackinsight_isin", "_fetch_trackinsight",
        "_fetch_issuer", "_fetch_justetf", "_fetch_equity_profile", "_fetch_yf_sectors",
    ),
    issuers: ("fetch", "fetch_ishares", "fetch_vanguard"),
    fx: ("_fetch_rates",),
    catalogue: ("_fetch_overview",),
    # The LLM is a network call like any other, and the only one with a key
    # attached: a test that forgets to fake it spends real money against the
    # real account. chain.py goes through call_llm, so one entry covers the
    # advisor and the chain together; the chat goes through its streaming
    # sibling, which is easier to reach by accident - a test that only checks
    # the first event has already paid for the whole answer. The public model
    # list, asked after a refusal, carries no key but is a call all the same.
    advisor: ("call_llm", "stream_llm", "_fetch_model_list"),
}


class NetworkReached(RuntimeError):
    """A test asked the outside world for something instead of faking it."""


def _refuse(module, name: str):
    def refuse(*args, **kwargs):
        raise NetworkReached(
            f"{module.__name__}.{name} was called for real. Fake it in the test: "
            "a suite that answers differently depending on whether you are "
            "online is not a measurement."
        )

    return refuse


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Refuse every network call, for every test.

    Autouse, so it is in place before the test body runs and any fake the test
    sets for itself wins over this one — this is the floor, not a policy about
    what a test may stub. Several call sites catch broadly and degrade, which
    is the point: a refusal here reproduces a real outage exactly, and does it
    the same way every time.

    Two module-level caches are reset with it, because they outlive a test and
    a faster suite makes that worse rather than better: the reachability
    verdict is cached for 20 seconds (once the whole run fits in a minute, that
    is a good share of it), and the justETF catalogue for 24 hours.
    """
    for module, helpers in _NETWORK_BOUNDARY.items():
        for name in helpers:
            monkeypatch.setattr(module, name, _refuse(module, name))
    prices._reset_reachability()
    monkeypatch.setattr(composition, "_CATALOGUE", None)
    monkeypatch.setattr(composition, "_CATALOGUE_AT", None)


@pytest.fixture(autouse=True)
def _no_catalogue_download_outlives_its_test(offline):
    """The fund catalogue downloads on a thread of its own (`catalogue.ensure`),
    so a test that starts one could end while it is still writing, into the
    next test's database, or after the fakes it was given have been put back.
    So every test starts from a process that has tried no download, and none
    may leave one running. After `offline`, so its fakes are still in place
    while the threads are waited for."""
    catalogue._forget()
    yield
    started = [t for t in threading.enumerate() if t.name == catalogue.THREAD_NAME]
    for thread in started:
        thread.join(timeout=5)
    catalogue._forget()
    assert not any(t.is_alive() for t in started), (
        "a catalogue download outlived its test: release whatever holds it"
    )


# --- A database the app has to migrate ----------------------------------------

# Everything above builds the schema straight from the models. These fixtures
# serve the tests about what a START does to a database file, which need the
# real migration chain and a file of their own, never the suite's.


@pytest.fixture(scope="session")
def _file_one_migration_behind(tmp_path_factory) -> pathlib.Path:
    """A file built by the real migration chain up to the revision before
    head, with a few rows in it: what the app finds on its first start after a
    commit that adds a migration.

    Built once (the chain takes about a second) and copied by every test that
    asks for one, so the tests follow the head wherever it moves. The Alembic
    config has no ini file on purpose: `env.py` then leaves Python's logging
    alone, whichever version of `env.py` is under test.
    """
    path = tmp_path_factory.mktemp("one_migration_behind") / "data.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    behind = script.get_revision(script.get_current_head()).down_revision
    assert isinstance(behind, str), "the chain's head is a merge; pick the revision by hand"
    with pytest.MonkeyPatch.context() as mp:
        # env.py reads the URL off app.database every time it runs.
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(cfg, behind)
    # Rows in two tables no migration has touched since the baseline, one of
    # them with a line break and non-ASCII text, so a copy that loses or
    # re-encodes anything shows in its dump.
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('base_currency', 'EUR')")
        conn.execute(
            "INSERT INTO institutions (name, type, notes, created_at) VALUES (?, ?, ?, ?)",
            ("Broker A", "broker", "Opened in 2019.\nFees: 2,95 € a trade.", "2026-09-29T10:00:00"),
        )
    return path


@pytest.fixture
def start_on(monkeypatch):
    """`start_on(path)`, then `database.init_db()`: the app starting on that
    file with migrations on, exactly as uvicorn's startup runs it."""
    engines = []

    def point_at(path: pathlib.Path) -> None:
        url = f"sqlite:///{path}"
        engines.append(create_engine(url))
        monkeypatch.setattr(database, "DATABASE_URL", url)
        monkeypatch.setattr(database, "engine", engines[-1])
        monkeypatch.delenv("AURELIO_SKIP_MIGRATIONS", raising=False)

    yield point_at
    # A pooled connection holds its file open, and Windows will not delete a
    # test's temp folder while it does.
    for eng in engines:
        eng.dispose()


@pytest.fixture(autouse=True)
def _uvicorn_console_as_found():
    """`main.say_why_not` adds a filter to the global uvicorn.error logger,
    which is right for a process about to exit. The test process goes on, so
    whatever a test added is taken off again, and no test can pass on a filter
    an earlier one left behind."""
    console = logging.getLogger("uvicorn.error")
    before = list(console.filters)
    yield
    console.filters[:] = before


@pytest.fixture
def one_migration_behind(_file_one_migration_behind, tmp_path, start_on) -> pathlib.Path:
    """A fresh copy of that file, named data.db like the reader's, which the
    next `database.init_db()` starts on."""
    path = tmp_path / "data.db"
    shutil.copyfile(_file_one_migration_behind, path)
    start_on(path)
    return path
