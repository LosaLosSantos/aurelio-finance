"""The demo: an invented household, built through the app's own API.

It is what a stranger opens first and what the README's screenshots show, so it
must need nothing of anyone's, build with no network, and never write into a
database that already exists, least of all `data.db`.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import demo

DAY = datetime.date(2026, 10, 6)
BACKEND = Path(__file__).resolve().parent.parent


def test_the_demo_is_built_through_the_api_with_no_network(client):
    """conftest refuses every outside call, so a build that asked Yahoo or the
    ECB for anything would raise here instead of passing."""
    ids = demo.populate(client, DAY)

    names = sorted(i["name"] for i in client.get("/api/institutions").json())
    assert names == ["Demo Bank", "Demo Broker"]
    holdings = client.get(f"/api/snapshots/{ids['situation']}/holdings").json()
    assert {h["asset_name"] for h in holdings} == {
        demo.WORLD["asset_name"], demo.EMERGING["asset_name"],
        demo.SHARE["asset_name"], demo.BONDS["asset_name"],
    }
    summary = client.get("/api/dashboard/summary").json()
    assert summary["net_worth"] > 0
    assert summary["unresolved_omissions"] == [], "the newer situation names every row"
    assert len(client.get("/api/survey").json()) == len(demo._survey())


def test_every_date_in_the_demo_is_counted_back_from_the_day_it_is_built(client):
    """So the demo always ends today. The plan is the one thing in the future:
    it starts next month, so it has bought nothing and asks no price."""
    demo.populate(client, DAY)
    (plan,) = client.get("/api/accumulation-plans").json()
    assert plan["start_date"] == "2026-11-05"
    (buy,) = client.get("/api/transactions").json()
    assert buy["date"] == "2026-09-16"
    situations = client.get(f"/api/institutions/{plan['source_institution_id']}/snapshots").json()
    assert sorted(s["date"] for s in situations) == ["2025-12-10", "2026-07-08"]


def test_the_demo_is_never_built_into_data_db(tmp_path):
    with pytest.raises(demo.DemoRefused, match="never built into data.db"):
        demo.build(tmp_path / "data.db", DAY)
    assert not (tmp_path / "data.db").exists()


def test_the_demo_is_never_written_over_a_file_that_exists(tmp_path):
    path = tmp_path / "demo.db"
    path.write_bytes(b"someone's file")
    with pytest.raises(demo.DemoRefused, match="already exists"):
        demo.build(path, DAY)
    assert path.read_bytes() == b"someone's file"


def test_the_demo_will_not_run_where_the_app_is_bound_to_another_database(tmp_path):
    """This process runs the app on the suite's database. Building the demo
    here would write into THAT, which is how a demo ends up in someone's
    records, so it refuses and creates nothing."""
    with pytest.raises(demo.DemoRefused, match="fresh one"):
        demo.build(tmp_path / "demo.db", DAY)
    assert not (tmp_path / "demo.db").exists()


# Run in a fresh process with every connection and name lookup that leaves the
# machine refused: the command as a stranger runs it, proved to reach nothing
# outside. Loopback stays open, because on Windows asyncio builds its own event
# loop out of a socket pair on 127.0.0.1. yfinance talks through libcurl, which
# never touches Python's sockets, so every proxy variable also points at a
# closed local port: libcurl and httpx both honour them (checked on 2026-10-06
# with a local listener standing in as the proxy, which received their CONNECTs
# to Yahoo and to Frankfurter).
_OFFLINE_MAIN = """
import socket, sys
LOCAL = {"127.0.0.1", "::1", "localhost"}
_connect, _getaddrinfo = socket.socket.connect, socket.getaddrinfo
def connect(self, address):
    if (address[0] if isinstance(address, tuple) else address) not in LOCAL:
        raise OSError(f"the demo reached the network: {address}")
    return _connect(self, address)
def getaddrinfo(host, *args, **kwargs):
    if host is not None and host not in LOCAL:
        raise OSError(f"the demo looked up {host}")
    return _getaddrinfo(host, *args, **kwargs)
socket.socket.connect = connect
socket.getaddrinfo = getaddrinfo
from app.demo import main
sys.exit(main(sys.argv[1:]))
"""


def _command(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("DATABASE_URL", "AURELIO_SKIP_MIGRATIONS")}
    closed = "http://127.0.0.1:9"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[name] = env[name.lower()] = closed
    env["NO_PROXY"] = env["no_proxy"] = ""
    return subprocess.run(
        [sys.executable, "-c", _OFFLINE_MAIN, *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180,
    )


def _head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_current_head()


def test_the_command_builds_a_new_file_at_the_head_revision_and_keeps_it(tmp_path):
    path = tmp_path / "demo.db"
    built = _command("--path", str(path))
    assert built.returncode == 0, built.stderr
    assert "Demo database built" in built.stdout

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert con.execute("select version_num from alembic_version").fetchone()[0] == _head()
        names = sorted(r[0] for r in con.execute("select name from institutions"))
        assert names == ["Demo Bank", "Demo Broker"]
    finally:
        con.close()

    before = hashlib.md5(path.read_bytes()).hexdigest()
    again = _command("--path", str(path), "--if-missing")
    assert again.returncode == 0 and "already there" in again.stdout
    refused = _command("--path", str(path))
    assert refused.returncode == 2 and "already exists" in refused.stderr
    assert hashlib.md5(path.read_bytes()).hexdigest() == before, "an existing demo was rewritten"
