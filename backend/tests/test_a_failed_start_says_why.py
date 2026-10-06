"""A start that fails says why.

`init_db` runs Alembic inside uvicorn's startup, and Alembic's `env.py`
configured logging from alembic.ini with `fileConfig`, whose default switches
off every logger that already exists, uvicorn's included. Measured on copies of
the test database at 24d6d39: a migration that failed at startup exited with
code 3 and not one word about it, and a start with nothing to migrate went
quiet after its fourth line. The app now asks Alembic to leave logging alone;
the `alembic` command line still configures it from alembic.ini.
"""

from __future__ import annotations

import logging

from app import database


def test_a_start_that_migrates_leaves_every_logger_on(one_migration_behind):
    # Loggers that exist before the start, the way uvicorn's and the app's do:
    # fileConfig only switches off the ones it finds already there.
    watched = [
        logging.getLogger(name)
        for name in ("uvicorn.error", "uvicorn.access", "app.catalogue")
    ]
    assert [logger.name for logger in watched if logger.disabled] == []

    database.init_db()

    assert [logger.name for logger in watched if logger.disabled] == []
