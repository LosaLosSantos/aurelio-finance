"""SQLite database configuration and SQLAlchemy session.

Schema is managed by Alembic migrations, applied automatically at app startup,
and never to a database that has not been copied first (see init_db). Tests
bypass migrations and build the schema straight from the models
(AURELIO_SKIP_MIGRATIONS=1).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Load backend/.env (if present) so secrets/config like OPENROUTER_API_KEY and
# DATABASE_URL are available via os.getenv. Defensive: works even if the
# python-dotenv package is not installed.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# backend/ = parent folder of app/ (this file is backend/app/database.py)
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data.db"

# Allow an override via environment variable, otherwise use backend/data.db
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

engine = create_engine(
    DATABASE_URL,
    # required with SQLite when connections are used from different threads (FastAPI)
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """Enable foreign key enforcement (cascade) on SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def get_db():
    """FastAPI dependency: provide a DB session per request and close it."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- A session that cannot write ------------------------------------------

# Kept in the session's own `info` dict, for the same reason the unit-of-work
# depth below is: two sessions never read each other's flags.
#
# It exists because SQLite can refuse a write for real — a connection opened
# `mode=ro` raises rather than trusting anybody's discipline — and code that
# opportunistically refreshes a cache would then raise instead of serving what
# it has. Such code asks here first. Set by `app/mcp_server.py`, whose whole
# contract is that an outside assistant reads and never writes.
READ_ONLY = "aurelio_read_only"


def read_only(db: Session) -> bool:
    """Whether this session has declared that it cannot write."""
    return bool(db.info.get(READ_ONLY))


# --- Transaction boundaries -----------------------------------------------

# How many units of work are open on a Session, kept in the session's own
# `info` dict so two sessions never read each other's depth.
_UNIT_DEPTH = "aurelio_unit_of_work_depth"


@contextmanager
def unit_of_work(db: Session) -> Iterator[Session]:
    """One operation, one transaction: commits on the way out, rolls back if
    the block raises.

    The CALLER decides what one operation is — a router for one request, the
    occurrence loop in the PAC catch-up for one fill — because only the caller
    knows where the boundary is. A write layer that commits once per call has
    already decided for everybody, and decided wrong: a PAC occurrence buying
    two funds committed the first leg on its own, so a crash before the second
    left the occurrence recorded as done with one fund unbought, on that run
    and every later one.

    Reentrant. A nested block flushes instead of committing, so the outermost
    one owns the transaction and the migration can be incremental: `commit()`
    below stays in every crud function and simply defers to whoever is holding
    a unit of work above it.
    """
    depth = db.info.get(_UNIT_DEPTH, 0)
    db.info[_UNIT_DEPTH] = depth + 1
    try:
        yield db
    except BaseException:
        if depth == 0:
            db.rollback()
        raise
    else:
        if depth:
            # Visible to the enclosing unit — it can read back what it just
            # wrote — and still undoable by it.
            db.flush()
        else:
            try:
                db.commit()
            except BaseException:
                # A commit that fails leaves the session unusable until it is
                # rolled back, and the caller is about to handle the error, not
                # the session.
                db.rollback()
                raise
    finally:
        db.info[_UNIT_DEPTH] = depth


def commit(db: Session) -> None:
    """Finish a write that owns no unit of work of its own.

    Standing alone this commits, exactly as the bare `db.commit()` it replaced.
    Inside a caller's `unit_of_work` it only flushes: the caller ends the
    transaction, and committing here would cut its unit in half.
    """
    if db.info.get(_UNIT_DEPTH):
        db.flush()
    else:
        db.commit()


@contextmanager
def sole_writer(db: Session) -> Iterator[Session]:
    """A unit of work that holds SQLite's write lock from before its first
    read: for a write that must ask, inside it, whether it is still needed.

    "Is it already recorded?" followed by a write is a question two callers can
    both answer "no" to. The app posts the ledger catch-up once per page load,
    so two tabs (or React's StrictMode on the development server) run it twice
    at once, and both wrote the same PAC buy and the same dividend. Measured on
    2026-09-30, both held between the question and the write: twice, 10 trials
    of 10, for each. An ordinary unit of work does not help: the driver begins
    SQLite's transaction only at the first write, so the question is asked
    holding nothing. `BEGIN IMMEDIATE` takes the lock first, so a second caller
    waits at its own `BEGIN IMMEDIATE` until this block commits or rolls back,
    and its question then sees what this one wrote.

    The lock is SQLite's, on the file, so it holds against another process as
    well as another thread, which a lock in Python would not. And while it is
    held every other write in the app waits, so the block does no slow work:
    whatever needs the network is asked BEFORE it opens.

    Only ever the outermost unit. Inside another one it would hold the lock
    for whatever that unit goes on to do, and the enclosing transaction may
    already have written, which `BEGIN IMMEDIATE` refuses.
    """
    if db.info.get(_UNIT_DEPTH):
        raise RuntimeError(
            "sole_writer cannot open inside a unit of work: it would hold the "
            "write lock for whatever the enclosing unit does next"
        )
    with unit_of_work(db):
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield db


# --- Startup: migrate, and never without a copy ---------------------------------

# Lines the reader should see at startup go to uvicorn's own logger: it is the
# one that prints "Application startup complete", so they sit among uvicorn's
# lines in the console. Outside uvicorn it has no handler and they go nowhere.
_console = logging.getLogger("uvicorn.error")

# How long each connection of a copy waits for another program to let go of a
# database file. Left alone, Python's `Connection.backup` retries a locked file
# forever (measured: still waiting after 15 seconds, both reading a locked file
# and writing one), and a start that waits forever says nothing. With this, the
# copy gives up, a little later than this in all (measured: 7.3 seconds with the
# source locked, 5.5 with a reader holding the target), hence "more than".
LOCK_WAIT_SECONDS = 5.0


class StartRefused(RuntimeError):
    """The app will not start on this database. The message is the sentence
    the reader sees: what happened, what was left as it was, and what to do."""


def _database_file() -> Path | None:
    """The file DATABASE_URL names, or None when it names none (in memory)."""
    name = make_url(DATABASE_URL).database
    return Path(name).resolve() if name and name != ":memory:" else None


def _reason(error: BaseException) -> object:
    """An error as the reader reads it: the operating system's words without
    the path it failed on (every sentence here names its files already), or
    the error itself."""
    return error.strerror if isinstance(error, OSError) and error.strerror else error


def _first_line(error: BaseException) -> str:
    """A failed migration in one line, in the database driver's own words:
    SQLAlchemy wraps the driver's error (keeping it as `orig`) in a text that
    runs on to the SQL statement and a link."""
    error = getattr(error, "orig", None) or error
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _give_up_when_locked(status: int, remaining: int, total: int) -> None:
    """`backup()` calls this after every step, including one that found the
    file locked, and raising here is the only way to stop its retries."""
    if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        raise TimeoutError(
            f"another program kept the file locked for more than {LOCK_WAIT_SECONDS:g} seconds"
        )


def _sqlite_copy(source: Path, target: Path) -> None:
    """Copy one SQLite database onto another, through SQLite, in one step.

    The online backup API, every page in one call. The source is opened
    read-only and read inside one read transaction, which SQLite's locks keep
    clear of any commit in progress elsewhere: the copy is always a state some
    commit left, never one caught halfway. The target is written inside one
    write transaction, under its own rollback journal. A plain file copy has
    neither guarantee: it takes no lock, and it would copy a crashed file
    without the journal that file needs.
    """
    src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=LOCK_WAIT_SECONDS)
    try:
        dst = sqlite3.connect(target, timeout=LOCK_WAIT_SECONDS)
        try:
            src.backup(dst, progress=_give_up_when_locked)
        finally:
            dst.close()
    finally:
        src.close()


def _copy_path(db: Path, frm: str, to: str) -> Path:
    """Where the copy taken before a migration goes: next to the file, named
    like the backups already made there by hand, and labelled with the two
    revisions. The `.db.bak-` in the name is what keeps it out of git."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return db.with_name(f"{db.name}.bak-{stamp}-before-migration-{frm}-to-{to}")


def _copy_before_migrating(db: Path | None, frm: str, to: str) -> Path:
    """Copy the database next to itself, or refuse to start.

    Written under a `.part` name and renamed once whole, so a file with the
    final name is always a complete copy, and never over a file already there.
    Nothing here deletes a copy, automatic or made by hand: a "keep the last N"
    rule fails exactly when it matters, when a migration that fails is retried
    and pushes the good copy out.
    """
    if db is None:
        raise StartRefused(
            f"Aurelio did not start: the database {DATABASE_URL} needs a migration "
            f"from {frm} to {to}, and it is not a file, so it cannot be copied first."
        )
    copy = _copy_path(db, frm, to)
    part = copy.with_name(copy.name + ".part")
    made = False
    try:
        with open(part, "xb"):
            made = True
        _sqlite_copy(db, part)
        if copy.exists():
            raise FileExistsError("a file with that name is already there")
        part.rename(copy)
    except (OSError, sqlite3.Error) as exc:
        if made:
            with suppress(OSError):
                part.unlink(missing_ok=True)
        raise StartRefused(
            f"Aurelio did not start, and {db.name} was not changed. It needs a "
            f"migration from {frm} to {to}, and the app copies the database before "
            f"every migration, but the copy to {copy} could not be made: "
            f"{_reason(exc)}. Start the app again once a copy can be made there."
        ) from None
    return copy


def _dump(path: Path) -> list[str]:
    """A database's whole content as SQL, read-only: what two files are
    compared by, since a copy's header counters start afresh."""
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=LOCK_WAIT_SECONDS)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def _put_back(db: Path, copy: Path, frm: str, to: str, failure: Exception) -> NoReturn:
    """Undo a migration that failed, from the copy taken just before it, and
    refuse to start, saying what state the file is in.

    On SQLite, Alembic commits one migration at a time ("Will assume
    non-transactional DDL"; measured: with two pending and the second failing,
    the file was left at the first). A failure can leave the file part-way,
    and a start after it would copy the part-way file. Writing the copy back
    makes every start migrate the file completely or leave it as it was.

    It is `_sqlite_copy` in the other direction: one backup call, one write
    transaction on the file under its rollback journal, so it lands whole or
    not at all. It waits on other programs the way the copy does and gives up
    the same way, leaving the file as the migration left it.

    Then the file is compared with the copy, whether the write-back worked or
    not, and the sentence says only what the comparison found: "as it was"
    after a match, "put it back by hand" after anything else. A migration that
    another program's lock stopped before it wrote leaves the file as it was
    even when the write-back is stopped too (measured), and it would be wrong
    to send the reader to restore a file that needs nothing.
    """
    # The migration's own error in full, for whoever runs uvicorn with
    # --log-level debug; the reader gets its first line.
    _console.debug("The migration's own error:", exc_info=failure)
    failed = (
        f"Aurelio did not start: the migration of {db.name} from {frm} to {to} "
        f"failed ({_first_line(failure)})."
    )
    again = (
        "Do not start the app again until the cause is fixed: each start "
        "would take another copy and fail the same way."
    )
    by_hand = (
        f"Put the copy {copy} back in place of {db.name} by hand before starting "
        "the app again, and do not start it until the cause is fixed."
    )
    try:
        _sqlite_copy(copy, db)
        not_written = None
    except (OSError, sqlite3.Error) as exc:
        not_written = _reason(exc)
    try:
        matches, mismatch = _dump(db) == _dump(copy), "the two do not match"
    except (OSError, sqlite3.Error) as exc:
        matches, mismatch = False, f"the two could not be compared ({_reason(exc)})"

    if matches and not_written is None:
        found = (
            f"{db.name} was put back exactly as it was before, from its copy "
            f"{copy}, which is kept. {again}"
        )
    elif matches:
        found = (
            f"Putting {db.name} back from its copy could not be done "
            f"({not_written}), but it matches the copy: the failed migration left "
            f"it as it was. The copy {copy} is kept. {again}"
        )
    elif not_written is None:
        found = (
            f"{db.name} was written back from its copy, but {mismatch}, so it may "
            f"not be as it was. {by_hand}"
        )
    else:
        found = (
            f"Putting {db.name} back from its copy failed too ({not_written}), and "
            f"{mismatch}, so it may be left part-way. {by_hand}"
        )
    raise StartRefused(f"{failed} {found}") from None


def init_db() -> None:
    """Bring the schema up to date at startup, via Alembic migrations, and
    never migrate a database that has not been copied first.

    - Tests set AURELIO_SKIP_MIGRATIONS=1 and get the schema straight from the
      models (fast, no migration files involved).
    - A database created before Alembic (tables but no alembic_version) is
      adopted in place: stamped as current, no data touched.
    - A database already at the code's head is left alone: nothing copied,
      nothing written, no Alembic command run. That is every ordinary start,
      and the file comes out of it byte-identical.
    - A revision this code does not have (the file was migrated by a newer
      version) is refused by Alembic before anything is copied.
    - A fresh, empty database is built by the migration chain with no copy:
      there is nothing in it to lose.
    - Anything else is copied next to itself first, and migrated only once the
      copy is whole. If it cannot be copied, StartRefused: the app does not
      start, and nothing is changed. If the migration fails, the copy is
      written back over the file and compared with it (`_put_back`), and the
      app does not start either: a start migrates the file completely or
      leaves it as it was.
    """
    from app import models  # noqa: F401  (register the models on Base.metadata)

    if os.getenv("AURELIO_SKIP_MIGRATIONS") == "1":
        Base.metadata.create_all(bind=engine)
        return

    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    # Logging belongs to uvicorn here, and Alembic configuring its own would
    # switch uvicorn's off (see alembic/env.py).
    cfg.attributes["configure_logger"] = False

    tables = inspect(engine).get_table_names()
    if tables and "alembic_version" not in tables:
        # Pre-Alembic database (made by create_all when models == head):
        # mark it as already migrated; the check below then finds nothing to do.
        command.stamp(cfg, "head")

    script = ScriptDirectory.from_config(cfg)
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_heads()
    heads = script.get_heads()
    if set(current) == set(heads):
        return
    for revision in current:
        script.get_revision(revision)  # one this code does not have raises here

    db = _database_file()
    frm, to = "+".join(current) or "base", "+".join(heads)
    if not tables:
        command.upgrade(cfg, "head")
        _console.info("Built a new database at %s, at revision %s.", db or DATABASE_URL, to)
        return
    copy = _copy_before_migrating(db, frm, to)
    _console.info("Copied %s to %s before migrating it.", db.name, copy)
    try:
        command.upgrade(cfg, "head")
    except Exception as failure:
        _put_back(db, copy, frm, to, failure)
    _console.info("Migrated %s to %s.", db.name, to)
