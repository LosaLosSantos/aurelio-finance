"""No migration runs on the reader's data without a copy of it.

Since 2026-09-29 backend/data.db holds real money, and init_db migrates it
unattended whenever a start finds a migration pending. What brief W part 1
decided, and what is pinned here:

- WHEN. A copy is taken only when a migration is pending AND the file holds at
  least one table. An ordinary start copies nothing and writes nothing; a new,
  empty database is built with no copy; a file at a revision this code does not
  have is refused by Alembic before anything is copied.
- HOW. SQLite's own backup API, the source opened read-only, every page in one
  step, so the copy is always a state some commit left. A file another program
  keeps locked makes it give up after LOCK_WAIT_SECONDS: left alone, Python's
  backup() waits forever (measured, still waiting after 15 seconds).
- WHERE. Next to the file, as
  data.db.bak-<date>-<time>-before-migration-<from>-to-<to>, written under a
  .part name and renamed once whole, never over a file already there.
- WHEN IT FAILS. The app does not start, nothing is changed, and the sentence
  says what happened and what to do.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app import database

COPY_NAME = re.compile(r"data\.db\.bak-\d{8}-\d{6}-before-migration-(\w+)-to-(\w+)")


def _config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    return cfg


def _head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def _revision(path: Path) -> str:
    with closing(_read_only(path)) as conn:
        [(revision,)] = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    return revision


def _dump(path: Path) -> list[str]:
    with closing(_read_only(path)) as conn:
        return list(conn.iterdump())


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _beside(db: Path) -> list[str]:
    """Every file next to the database, but the database itself."""
    return sorted(p.name for p in db.parent.iterdir() if p != db)


# --- When -----------------------------------------------------------------------


def test_a_pending_migration_is_copied_first(one_migration_behind):
    db = one_migration_behind
    behind, before = _revision(db), _dump(db)

    database.init_db()

    [name] = _beside(db)
    match = COPY_NAME.fullmatch(name)
    assert match, name
    assert match.groups() == (behind, _head())
    # The copy holds the database exactly as it was before the migration.
    assert _dump(db.parent / name) == before
    assert _revision(db) == _head()


def test_an_ordinary_start_copies_nothing_and_leaves_the_file_byte_identical(one_migration_behind):
    # The reader's data.db on every start of every day: already at head.
    db = one_migration_behind
    command.upgrade(_config(), "head")  # Alembic itself, so no copy is involved
    assert _revision(db) == _head()
    md5 = _md5(db)

    database.init_db()

    assert _beside(db) == []
    assert _md5(db) == md5


def test_a_new_database_is_built_with_no_copy(tmp_path, start_on):
    db = tmp_path / "data.db"
    start_on(db)

    database.init_db()

    assert _revision(db) == _head()
    assert _beside(db) == []


def test_a_revision_this_code_does_not_have_is_refused_before_any_copy(one_migration_behind):
    # A file migrated by a newer version of the app, then started by an older one.
    db = one_migration_behind
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE alembic_version SET version_num = 'ffffffffffff'")
    md5 = _md5(db)

    with pytest.raises(Exception, match="ffffffffffff"):
        database.init_db()

    assert _beside(db) == []
    assert _md5(db) == md5


# --- When the copy cannot be made -----------------------------------------------


def test_a_copy_that_cannot_be_made_stops_the_migration(one_migration_behind, monkeypatch, tmp_path):
    db = one_migration_behind
    behind, md5 = _revision(db), _md5(db)
    # Into a folder that does not exist: the operating system refuses the file.
    missing = tmp_path / "missing" / "data.db.bak-copy"
    monkeypatch.setattr(database, "_copy_path", lambda *_: missing)

    with pytest.raises(database.StartRefused) as refused:
        database.init_db()

    assert _md5(db) == md5
    assert _revision(db) == behind
    assert _beside(db) == []
    sentence = str(refused.value)
    for words in (
        "Aurelio did not start, and data.db was not changed.",
        f"from {behind} to {_head()}",
        str(missing),
        "No such file or directory",
        "Start the app again once a copy can be made there.",
    ):
        assert words in sentence


def test_a_file_another_program_keeps_locked_stops_the_start_instead_of_hanging(
    one_migration_behind, monkeypatch
):
    db = one_migration_behind
    md5 = _md5(db)
    monkeypatch.setattr(database, "LOCK_WAIT_SECONDS", 0.2)
    real_copy = database._sqlite_copy

    def copy_while_another_program_holds_the_file(source, target):
        holder = sqlite3.connect(source, isolation_level=None)
        holder.execute("BEGIN EXCLUSIVE")
        try:
            real_copy(source, target)
        finally:
            holder.close()

    monkeypatch.setattr(database, "_sqlite_copy", copy_while_another_program_holds_the_file)
    outcome = {}

    def start():
        try:
            database.init_db()
        except Exception as exc:  # the thread's result, read below
            outcome["raised"] = exc

    # In a thread, so a copy that waits forever fails this test instead of
    # hanging the suite.
    starting = threading.Thread(target=start, daemon=True)
    starting.start()
    starting.join(timeout=30)

    assert not starting.is_alive(), "the start was still waiting after 30 seconds"
    assert isinstance(outcome.get("raised"), database.StartRefused)
    # "More than": each connection waits this long, and the copy as a whole
    # a little longer (7.3 seconds measured at the real 5).
    assert "kept the file locked for more than 0.2 seconds" in str(outcome["raised"])
    assert _beside(db) == []  # the .part it had started is gone
    assert _md5(db) == md5


def test_a_copy_never_replaces_a_file_already_there(one_migration_behind, monkeypatch):
    db = one_migration_behind
    md5 = _md5(db)
    taken = db.with_name("data.db.bak-taken")
    taken.write_bytes(b"not a copy of anything")
    monkeypatch.setattr(database, "_copy_path", lambda *_: taken)

    # On Windows the rename refuses by itself; on Linux, where CI runs, it
    # would replace the file in silence, and only the app's own check stops it.
    with pytest.raises(database.StartRefused):
        database.init_db()

    assert taken.read_bytes() == b"not a copy of anything"
    assert _beside(db) == ["data.db.bak-taken"]  # and no .part left
    assert _md5(db) == md5


def test_a_refused_start_is_said_in_one_sentence_not_under_a_traceback(caplog):
    # Measured on a copy with start.ps1's command: left to itself, uvicorn put
    # the sentence at the bottom of 139 lines, one frame pair for each of the
    # 20 routers FastAPI wraps the lifespan in.
    # The filter this adds is taken off again by conftest's
    # _uvicorn_console_as_found.
    from app import main

    console = logging.getLogger("uvicorn.error")
    sentence = "Aurelio did not start, and data.db was not changed."
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        main.say_why_not(database.StartRefused(sentence))
    assert [record.getMessage() for record in caplog.records] == [sentence]

    # What uvicorn logs next: the traceback Starlette formats for the
    # refusal, then its own line.
    def record(message: str) -> logging.LogRecord:
        return console.makeRecord(console.name, logging.ERROR, __file__, 0, message, None, None)

    assert not console.filter(record(f"Traceback (most recent call last):\n...\napp.database.StartRefused: {sentence}"))
    assert console.filter(record("Application startup failed. Exiting."))
