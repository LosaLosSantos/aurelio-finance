"""A migration that never ended is said at the next start, with the copy taken
before it.

Brief W part 1's put-back (`database._put_back`) writes the copy back when a
migration fails, from inside the process that failed. A process that dies
while it migrates (killed, its window closed, the power cut) never gets
there. Measured at `c61e5bc` (brief BE), with the death simulated on the
suite's file one migration behind (the head migration's table made,
Alembic's stamp never written): the next start copied the part-way file,
failed on the table already there, said the file "was put back exactly as it
was before" from that copy of itself, and named it, not the copy taken
before the first migration.

Now a migration marks itself beside its copy while it runs, and a start that
finds the mark refuses and names that copy, unless the file reached the
migration's revision or is the copy itself.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command

from app import database


class _Died(BaseException):
    """The process ending mid-migration: nothing in it catches this."""


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _beside(db: Path) -> list[Path]:
    return sorted(p for p in db.parent.iterdir() if p != db)


def _revision(path: Path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        [(revision,)] = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    return revision


def _head_table(db: Path) -> None:
    """What the head migration does, without Alembic's stamp after it."""
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            "CREATE TABLE fx_rates_yahoo (currency VARCHAR NOT NULL, as_of VARCHAR NOT NULL,"
            " rate FLOAT NOT NULL, fetched_at VARCHAR NOT NULL, PRIMARY KEY (currency, as_of))"
        )


def _dies_mid_migration(monkeypatch, db: Path) -> None:
    def upgrade(cfg, revision):
        _head_table(db)
        raise _Died()

    monkeypatch.setattr(command, "upgrade", upgrade)


@pytest.fixture
def died(one_migration_behind, monkeypatch) -> dict:
    """A start that copied the file, marked its migration, half did it and
    died; Alembic as it really is for the next start."""
    db = one_migration_behind
    behind = _revision(db)
    real = command.upgrade
    _dies_mid_migration(monkeypatch, db)
    with pytest.raises(_Died):
        database.init_db()
    monkeypatch.setattr(command, "upgrade", real)
    (copy, mark) = _beside(db)
    return {"db": db, "behind": behind, "copy": copy, "mark": mark}


def test_the_start_after_a_death_names_the_copy_taken_before_it(died):
    db, copy, mark = died["db"], died["copy"], died["mark"]
    assert mark.name == copy.name + ".migrating"
    md5 = _md5(db)

    with pytest.raises(database.StartRefused) as refused:
        database.init_db()

    head = json.loads(mark.read_text(encoding="utf-8"))["to"]
    assert str(refused.value) == (
        "Aurelio did not start, and data.db was not changed: the last start stopped in the "
        f"middle of migrating it from {died['behind']} to {head}, so the file may be part-way. "
        f"Put the copy taken just before that migration, {copy}, in place of data.db, then "
        "start the app again."
    )
    assert _beside(db) == [copy, mark], "no second copy"
    assert _md5(db) == md5


def test_the_copy_put_back_by_hand_is_migrated_again(died, monkeypatch):
    db, copy = died["db"], died["copy"]
    shutil.copyfile(copy, db)
    # The second copy's name: copies are named by the second, and this start
    # comes in the same one as the first.
    monkeypatch.setattr(
        database, "_copy_path", lambda d, frm, to: d.with_name(f"{d.name}.bak-second-{frm}-to-{to}")
    )

    database.init_db()

    assert _revision(db) != died["behind"]
    assert [p for p in _beside(db) if p.name.endswith(".migrating")] == []


def test_a_mark_whose_copy_is_gone_says_so(died):
    db, copy, mark = died["db"], died["copy"], died["mark"]
    copy.unlink()

    with pytest.raises(database.StartRefused) as refused:
        database.init_db()

    said = str(refused.value)
    assert f"the copy taken just before, {copy}, is not there any more" in said
    assert f"delete {mark}" in said


def test_a_migration_that_ends_leaves_no_mark(one_migration_behind):
    db = one_migration_behind

    database.init_db()

    assert [p.name.endswith(".migrating") for p in _beside(db)] == [False]


def test_a_mark_whose_migration_ended_is_taken_away(one_migration_behind):
    """The process died after Alembic's stamp and before the mark went."""
    db = one_migration_behind
    behind = _revision(db)
    database.init_db()
    (copy,) = _beside(db)
    mark = copy.with_name(copy.name + ".migrating")
    mark.write_text(json.dumps({"from": behind, "to": _revision(db)}), encoding="utf-8")
    md5 = _md5(db)

    database.init_db()

    assert _beside(db) == [copy]
    assert _md5(db) == md5


def test_a_failed_migration_put_back_leaves_no_mark(one_migration_behind, monkeypatch):
    db = one_migration_behind

    def upgrade(cfg, revision):
        raise RuntimeError("a migration that fails before it writes")

    monkeypatch.setattr(command, "upgrade", upgrade)
    with pytest.raises(database.StartRefused, match="was put back exactly as it was before"):
        database.init_db()

    assert [p.name.endswith(".migrating") for p in _beside(db)] == [False]


def test_a_put_back_that_could_not_restore_the_file_keeps_the_mark(one_migration_behind, monkeypatch):
    db = one_migration_behind
    real_copy, real_upgrade = database._sqlite_copy, command.upgrade

    def upgrade(cfg, revision):
        _head_table(db)
        raise RuntimeError("a migration that fails half way")

    def copy_but_never_back(source, target):
        if source.name == "data.db":
            return real_copy(source, target)
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(command, "upgrade", upgrade)
    monkeypatch.setattr(database, "_sqlite_copy", copy_but_never_back)
    with pytest.raises(database.StartRefused, match="may be left part-way"):
        database.init_db()
    (copy, mark) = _beside(db)
    assert mark.name == copy.name + ".migrating"

    monkeypatch.setattr(command, "upgrade", real_upgrade)
    monkeypatch.setattr(database, "_sqlite_copy", real_copy)
    with pytest.raises(database.StartRefused, match="stopped in the middle of migrating it"):
        database.init_db()
