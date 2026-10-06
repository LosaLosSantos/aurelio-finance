"""A migration that fails is undone from its copy.

On SQLite, Alembic commits one migration at a time ("Will assume
non-transactional DDL"). Measured on a copy of the test database: with two
migrations pending and the second failing, the file was left at the first, and
a start after that would copy the part-way file. The rule the reader chose: a
start either migrates the file completely or leaves it exactly as it was. So a
failed migration is followed by the copy written back over the file, and by a
comparison of the two before any sentence says the file is as it was.

The chain here is made for the tests, so they do not depend on what the real
head migration does: step zero holds the reader's rows, step one changes them
and adds a table, step two fails on a table that does not exist.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app import database

STEP_ZERO, STEP_ONE, STEP_TWO = "c000000000a0", "c000000000a1", "c000000000a2"

_STEP = '''"""{doc}"""
import sqlalchemy as sa
from alembic import op

revision = "{revision}"
down_revision = {down}
branch_labels = None
depends_on = None


def upgrade():
{body}


def downgrade():
    pass
'''

_STEPS = [
    (STEP_ZERO, None, "The reader's rows.",
     '    op.create_table("reader_rows", sa.Column("id", sa.Integer, primary_key=True), '
     'sa.Column("what", sa.String))'),
    (STEP_ONE, STEP_ZERO, "Changes the reader's rows and adds a table.",
     '    op.execute("UPDATE reader_rows SET what = what || \' (changed by step one)\'")\n'
     '    op.create_table("added_by_step_one", sa.Column("id", sa.Integer, primary_key=True))'),
    (STEP_TWO, STEP_ONE, "Fails.",
     '    op.execute("ALTER TABLE no_such_table ADD COLUMN x INTEGER")'),
]


@pytest.fixture(scope="session")
def _chain(tmp_path_factory) -> dict[str, Path]:
    """A backend folder whose migrations are the three steps above, with the
    real env.py and alembic.ini; a file at step zero holding the reader's rows;
    and, for comparison, what that file becomes after step one alone."""
    root = tmp_path_factory.mktemp("failing_chain")
    real = database.BASE_DIR
    shutil.copyfile(real / "alembic.ini", root / "alembic.ini")
    (root / "alembic" / "versions").mkdir(parents=True)
    shutil.copyfile(real / "alembic" / "env.py", root / "alembic" / "env.py")
    for revision, down, doc, body in _STEPS:
        (root / "alembic" / "versions" / f"{revision}.py").write_text(
            _STEP.format(doc=doc, revision=revision, down=repr(down), body=body),
            encoding="utf-8",
        )

    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    at_step_zero, after_step_one = root / "at_step_zero.db", root / "after_step_one.db"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{at_step_zero}")
        command.upgrade(cfg, STEP_ZERO)
        with closing(sqlite3.connect(at_step_zero)) as conn, conn:
            conn.executemany(
                "INSERT INTO reader_rows (what) VALUES (?)",
                [("VWCE x 10 at Broker A",), ("Opened in 2019.\nFees: 2,95 € a trade.",)],
            )
        shutil.copyfile(at_step_zero, after_step_one)
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{after_step_one}")
        command.upgrade(cfg, STEP_ONE)
    return {"root": root, "at_step_zero": at_step_zero, "after_step_one": after_step_one}


@pytest.fixture
def failing(_chain, tmp_path, start_on, monkeypatch) -> Path:
    """A fresh data.db at step zero, which the next `database.init_db()`
    starts on, with steps one and two pending and step two bound to fail."""
    db = tmp_path / "data.db"
    shutil.copyfile(_chain["at_step_zero"], db)
    start_on(db)
    monkeypatch.setattr(database, "BASE_DIR", _chain["root"])
    return db


def _dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return list(conn.iterdump())


def _beside(db: Path) -> list[Path]:
    return sorted(p for p in db.parent.iterdir() if p != db)


def _another_program_reads_during_the_put_back(monkeypatch) -> None:
    """While the copy is written back, a reader holds the file: the put-back
    meets a real lock, and gives up after LOCK_WAIT_SECONDS (0.2 here)."""
    monkeypatch.setattr(database, "LOCK_WAIT_SECONDS", 0.2)
    real_copy = database._sqlite_copy

    def copy_or_put_back(source, target):
        if source.name == "data.db":  # the copy before the migration: left alone
            return real_copy(source, target)
        reader = sqlite3.connect(target, isolation_level=None)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM reader_rows").fetchall()
        try:
            return real_copy(source, target)
        finally:
            reader.close()

    monkeypatch.setattr(database, "_sqlite_copy", copy_or_put_back)


def _start_in_a_thread() -> BaseException | None:
    """`database.init_db()`, in a thread, so a put-back that waits forever fails
    the test instead of hanging the suite. Returns what it raised."""
    outcome = {}

    def start():
        try:
            database.init_db()
        except Exception as exc:  # the thread's result, returned below
            outcome["raised"] = exc

    starting = threading.Thread(target=start, daemon=True)
    starting.start()
    starting.join(timeout=30)
    assert not starting.is_alive(), "the start was still waiting after 30 seconds"
    return outcome.get("raised")


def test_a_failed_migration_leaves_the_file_exactly_as_it_was(failing):
    before = _dump(failing)

    with pytest.raises(database.StartRefused) as refused:
        database.init_db()

    assert _dump(failing) == before
    [copy] = _beside(failing)
    assert _dump(copy) == before
    sentence = str(refused.value)
    for words in (
        f"the migration of data.db from {STEP_ZERO} to {STEP_TWO} failed",
        "no such table: no_such_table",
        f"data.db was put back exactly as it was before, from its copy {copy}, which is kept.",
        "Do not start the app again until the cause is fixed",
    ):
        assert words in sentence


def test_a_second_failed_start_leaves_it_as_it_was_again(failing, monkeypatch):
    # Named apart, since two starts can fall within one second in a test.
    names = iter(["first", "second"])
    monkeypatch.setattr(database, "_copy_path", lambda db, frm, to: db.with_name(f"{db.name}.bak-{next(names)}"))
    before = _dump(failing)

    for _ in range(2):
        with pytest.raises(database.StartRefused):
            database.init_db()

    # Each attempt starts from the same file, copies the same content, and
    # leaves the file as it found it: the copies pile up, the file does not drift.
    assert [p.name for p in _beside(failing)] == ["data.db.bak-first", "data.db.bak-second"]
    assert _dump(failing.with_name("data.db.bak-first")) == before
    assert _dump(failing.with_name("data.db.bak-second")) == before
    assert _dump(failing) == before


def test_a_put_back_another_program_blocks_leaves_the_file_as_the_migration_left_it(
    failing, _chain, monkeypatch
):
    before = _dump(failing)
    _another_program_reads_during_the_put_back(monkeypatch)

    refused = _start_in_a_thread()

    assert isinstance(refused, database.StartRefused)
    # Not torn: exactly the file the failed migration left, step one applied.
    assert _dump(failing) == _dump(_chain["after_step_one"])
    [copy] = _beside(failing)
    assert _dump(copy) == before
    sentence = str(refused)
    for words in (
        "Putting data.db back from its copy failed too",
        "kept the file locked for more than 0.2 seconds",
        "the two do not match, so it may be left part-way.",
        f"Put the copy {copy} back in place of data.db by hand",
        "do not start it until the cause is fixed",
    ):
        assert words in sentence
    assert "as it was" not in sentence


def test_a_put_back_that_is_not_needed_is_not_asked_for(failing, _chain, monkeypatch):
    # Already at step one, so the one pending step fails before writing
    # anything; the put-back is blocked, and the comparison finds nothing to do.
    shutil.copyfile(_chain["after_step_one"], failing)
    before = _dump(failing)
    _another_program_reads_during_the_put_back(monkeypatch)

    refused = _start_in_a_thread()

    assert isinstance(refused, database.StartRefused)
    assert _dump(failing) == before
    [copy] = _beside(failing)
    sentence = str(refused)
    for words in (
        f"from {STEP_ONE} to {STEP_TWO} failed (no such table: no_such_table)",
        "could not be done (another program kept the file locked for more than 0.2 seconds)",
        "but it matches the copy: the failed migration left it as it was.",
        f"The copy {copy} is kept.",
        "Do not start the app again until the cause is fixed",
    ):
        assert words in sentence
    assert "by hand" not in sentence


def test_a_put_back_that_did_not_take_is_not_reported_as_one(failing, monkeypatch):
    real_copy = database._sqlite_copy

    def put_back_that_writes_nothing(source, target):
        if source.name == "data.db":
            return real_copy(source, target)
        return None

    monkeypatch.setattr(database, "_sqlite_copy", put_back_that_writes_nothing)

    with pytest.raises(database.StartRefused) as refused:
        database.init_db()

    [copy] = _beside(failing)
    sentence = str(refused.value)
    assert "the two do not match" in sentence
    assert f"Put the copy {copy} back in place of data.db by hand" in sentence
    assert "was put back exactly" not in sentence
