"""The catalogue is always there, and nobody presses a button for it.

Brief AB. Every page load asks the backend to make sure the fund catalogue is
there (`POST /api/instruments/catalogue/ensure`), and the backend decides: a
download starts, on a thread of its own, only when the catalogue is empty,
undated or a week old, and only if none is running, and the page is answered
at once. justETF is faked throughout: `_fetch_overview` is the one helper that
would reach it, and the suite's network boundary refuses it.
"""

from __future__ import annotations

import datetime
import json
import threading
import time

import pandas as pd
import pytest
from justetf_scraping.helpers import STRATEGIES

from app import advisor, catalogue, chat, tools
from app.database import SessionLocal

NOW = datetime.datetime(2026, 10, 4, 12, 0, tzinfo=datetime.timezone.utc)
TYPES = tuple(STRATEGIES.values())
STALLED = catalogue.STALLED_AFTER
PAUSE = catalogue.PAUSE_AFTER_FAILURE


def _funds(n: int, types: tuple[str, ...] = TYPES, first: int = 0) -> pd.DataFrame:
    """n funds shaped as justETF's screener, each of a fund type in turn."""
    numbers = range(first, first + n)
    return pd.DataFrame(
        [
            {"name": f"Fund {i} UCITS ETF", "ticker": f"F{i}", "dividends": "Accumulating",
             "strategy": types[i % len(types)]}
            for i in numbers
        ],
        index=pd.Index([f"IE{i:010d}" for i in numbers], name="isin"),
    )


class Source:
    """justETF, faked. Answers in turn from `answers` (a catalogue, or an
    exception to raise), counts every ask, and holds the asks numbered in
    `holding` until the test releases them."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0
        self.held: set[int] = set()
        self.asked = threading.Event()
        self.release = threading.Event()

    def holding(self, *calls: int) -> Source:
        self.held = set(calls)
        return self

    def __call__(self):
        self.calls += 1
        number = self.calls
        answer = self.answers[min(number, len(self.answers)) - 1]
        self.asked.set()
        if number in self.held:
            assert self.release.wait(5), "the test never released the download"
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def clock(monkeypatch):
    """The catalogue's clock, moved by hand: `clock.now = ...`."""

    class Clock:
        now = NOW

    moved = Clock()
    monkeypatch.setattr(catalogue, "_now", lambda: moved.now)
    return moved


def _ensure(client) -> dict:
    """What a page load posts."""
    answered = client.post("/api/instruments/catalogue/ensure")
    assert answered.status_code == 200, answered.text
    return answered.json()


def _status(client) -> dict:
    return client.get("/api/instruments/catalogue").json()


def _finish() -> None:
    """Wait for the downloads a test started."""
    for thread in threading.enumerate():
        if thread.name == catalogue.THREAD_NAME:
            thread.join(timeout=5)


def _wait_until(condition) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "never happened"
        time.sleep(0.01)


def _seed(client, monkeypatch, clock, funds: pd.DataFrame, at: datetime.datetime) -> None:
    """A catalogue downloaded at `at`, loaded the way the suite loads one."""
    clock.now = at
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: funds)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    clock.now = NOW


def _call(name: str, **arguments) -> advisor.ToolCall:
    return advisor.ToolCall(id="call_1", name=name, arguments=json.dumps(arguments))


# --- when it downloads ---------------------------------------------------------


def test_an_empty_catalogue_downloads_by_itself_and_the_page_is_answered_at_once(
    client, monkeypatch, clock
):
    """The first page load finds nothing and starts a download. The page is
    answered while justETF is still being asked, so no page waits on it."""
    source = Source(_funds(6)).holding(1)
    monkeypatch.setattr(catalogue, "_fetch_overview", source)

    first = _ensure(client)
    assert first["rows"] == 0 and first["state"] == "downloading"
    assert source.asked.wait(5)
    source.release.set()
    _finish()

    after = _status(client)
    assert after["rows"] == 6 and after["state"] == "ready"
    assert after["fetched_at"] == NOW.isoformat(timespec="seconds")
    assert _ensure(client)["state"] == "ready"
    _finish()
    assert source.calls == 1, "a fresh catalogue is not downloaded again"


@pytest.mark.parametrize(
    "age, downloads",
    [
        (datetime.timedelta(days=1), 0),
        (catalogue.MAX_AGE - datetime.timedelta(minutes=1), 0),
        (catalogue.MAX_AGE, 1),
        (datetime.timedelta(days=30), 1),
    ],
)
def test_a_catalogue_is_downloaded_again_once_it_is_a_week_old(
    client, monkeypatch, clock, age, downloads
):
    """Funds launch and close every month: a week bounds how long a closed one
    stays suggestible, and a fresher catalogue is left alone."""
    _seed(client, monkeypatch, clock, _funds(5), NOW - age)
    source = Source(_funds(6))
    monkeypatch.setattr(catalogue, "_fetch_overview", source)

    _ensure(client)
    _finish()

    assert source.calls == downloads
    assert _status(client)["rows"] == (6 if downloads else 5)


def test_starting_the_app_downloads_nothing_and_the_suite_cannot_reach_justetf(client):
    """The test client runs the app's start as uvicorn does, and no download
    begins there: it is the page that asks. Asked with the suite's network
    boundary in place, the download is refused at the helper, recorded as a
    failure, and nothing is written."""
    assert not [t for t in threading.enumerate() if t.name == catalogue.THREAD_NAME]
    assert _status(client)["state"] == "not_started"

    _ensure(client)
    _finish()

    after = _status(client)
    assert after["state"] == "failed" and after["rows"] == 0
    assert catalogue._last.failure.startswith("NetworkReached")


# --- never twice at once ---------------------------------------------------------


def test_two_page_loads_at_once_download_once(client, monkeypatch, clock):
    """Two tabs, or React's StrictMode running the start effect twice on the
    development server: the second is told a download is running and starts
    none, and a download by hand is refused while it runs."""
    source = Source(_funds(6)).holding(1)
    monkeypatch.setattr(catalogue, "_fetch_overview", source)

    assert _ensure(client)["state"] == "downloading"
    assert source.asked.wait(5)
    assert _ensure(client)["state"] == "downloading"
    by_hand = client.post("/api/instruments/catalogue/refresh")
    assert by_hand.status_code == 409 and "already running" in by_hand.json()["detail"]
    source.release.set()
    _finish()

    assert source.calls == 1
    assert _status(client)["rows"] == 6


def test_of_callers_released_at_the_same_instant_exactly_one_downloads(monkeypatch, clock):
    """The claim itself, without HTTP in between: eight page loads let go
    together from a barrier, each with its own session."""
    source = Source(_funds(6))
    monkeypatch.setattr(catalogue, "_fetch_overview", source)
    barrier = threading.Barrier(8)

    def page_load():
        with SessionLocal() as db:
            barrier.wait(5)
            catalogue.ensure(db)

    loads = [threading.Thread(target=page_load) for _ in range(8)]
    for load in loads:
        load.start()
    for load in loads:
        load.join(5)
    _finish()

    assert source.calls == 1


# --- a failure keeps what was there, and waits before asking again ----------------


def test_a_failed_download_keeps_the_rows_and_waits_before_the_next_try(
    client, monkeypatch, clock
):
    """justETF did not answer. The week-old catalogue stays searchable, the
    failure is said, and the page loads that follow ask nothing until the pause
    is over, so reloads cannot hammer the source. The next one after it tries
    again, and this time the catalogue arrives."""
    _seed(client, monkeypatch, clock, _funds(5), NOW - datetime.timedelta(days=8))
    source = Source(ConnectionError("justETF did not answer"), _funds(6))
    monkeypatch.setattr(catalogue, "_fetch_overview", source)

    _ensure(client)
    _finish()
    failed = _status(client)
    assert failed["state"] == "failed" and failed["rows"] == 5
    assert failed["retry_after"] == (NOW + PAUSE).isoformat(timespec="seconds")
    assert client.get("/api/instruments/search", params={"q": "Fund 3"}).json()["families"]

    clock.now = NOW + PAUSE - datetime.timedelta(seconds=1)
    _ensure(client)
    _finish()
    assert source.calls == 1, "a reload inside the pause asks nothing"

    clock.now = NOW + PAUSE
    _ensure(client)
    _finish()
    assert source.calls == 2
    after = _status(client)
    assert after["rows"] == 6 and after["state"] == "ready"


def test_justetf_sending_no_funds_is_a_failure_and_the_rows_stay(client, monkeypatch, clock):
    """Read in the library: a page it cannot parse makes it assume a counter of
    0 and hand back an empty table without raising. Stored as it came, that
    would empty a full catalogue with nobody watching."""
    _seed(client, monkeypatch, clock, _funds(5), NOW - datetime.timedelta(days=8))
    monkeypatch.setattr(catalogue, "_fetch_overview", Source(pd.DataFrame()))

    _ensure(client)
    _finish()

    after = _status(client)
    assert after["state"] == "failed" and after["rows"] == 5
    assert catalogue._last.failure == "justETF sent no funds"


@pytest.mark.parametrize("brought, written", [(899, False), (900, True)])
def test_a_download_much_smaller_than_a_full_catalogue_is_refused(
    client, monkeypatch, clock, brought, written
):
    """Under nine tenths of a full catalogue, a download has lost a whole fund
    type or been cut short, and the stored one stays. Nine tenths passes."""
    _seed(client, monkeypatch, clock, _funds(1000), NOW - datetime.timedelta(days=8))
    monkeypatch.setattr(catalogue, "_fetch_overview", Source(_funds(brought, first=5000)))

    _ensure(client)
    _finish()

    after = _status(client)
    if written:
        assert after["rows"] == brought and after["state"] == "ready"
    else:
        assert after["rows"] == 1000 and after["state"] == "failed"


@pytest.mark.parametrize("lost", TYPES)
def test_a_fund_type_that_comes_back_empty_is_refused(client, monkeypatch, clock, lost):
    """Each type is its own request, and one answered with an empty list
    raises nothing. Losing Short & Leveraged (146 of 4,612 funds on
    2026-10-04) would leave 96.8%, which no floor can tell from churn, so every
    type is checked by name."""
    _seed(client, monkeypatch, clock, _funds(1000), NOW - datetime.timedelta(days=8))
    kept = tuple(t for t in TYPES if t != lost)
    monkeypatch.setattr(catalogue, "_fetch_overview", Source(_funds(990, kept, first=5000)))

    _ensure(client)
    _finish()

    after = _status(client)
    assert after["state"] == "failed" and after["rows"] == 1000
    assert lost in catalogue._last.failure


def test_an_empty_catalogue_takes_a_download_that_lacks_a_fund_type(client, monkeypatch, clock):
    """The checks protect a catalogue worth keeping. With nothing stored, 96.8%
    of the funds beats none of them, and refusing it would refuse it again at
    every try for as long as the type stays missing."""
    kept = tuple(t for t in TYPES if t != "Short & Leveraged")
    monkeypatch.setattr(catalogue, "_fetch_overview", Source(_funds(990, kept)))

    _ensure(client)
    _finish()

    after = _status(client)
    assert after["rows"] == 990 and after["state"] == "ready"


def test_a_small_registry_may_lose_a_fund(client, monkeypatch, clock):
    """The floor protects a catalogue of justETF's size. In a four-fund
    registry one fund leaving is a quarter of it, and it is a fund that left
    the market, not a broken download."""
    _seed(client, monkeypatch, clock, _funds(4), NOW - datetime.timedelta(days=8))
    monkeypatch.setattr(catalogue, "_fetch_overview", Source(_funds(3)))

    _ensure(client)
    _finish()

    after = _status(client)
    assert after["rows"] == 3 and after["state"] == "ready"


# --- a download that hangs ---------------------------------------------------------


def test_a_download_past_five_minutes_has_failed_and_still_writes_if_it_finishes(
    client, monkeypatch, clock
):
    """justETF's requests carry no timeout, so "downloading" could otherwise be
    said for ever. Past STALLED_AFTER the download counts as failed and the
    pause runs from there. If it then finishes, what it brought is a whole
    screener, and it is written."""
    source = Source(_funds(6)).holding(1)
    monkeypatch.setattr(catalogue, "_fetch_overview", source)
    _ensure(client)
    assert source.asked.wait(5)

    clock.now = NOW + STALLED
    stalled = _status(client)
    assert stalled["state"] == "failed"
    assert stalled["retry_after"] == (NOW + STALLED + PAUSE).isoformat(timespec="seconds")
    clock.now = NOW + STALLED + PAUSE - datetime.timedelta(seconds=1)
    _ensure(client)
    assert source.calls == 1, "inside the pause nothing else is asked"

    source.release.set()
    _finish()
    after = _status(client)
    assert after["rows"] == 6 and after["state"] == "ready"


def test_a_late_download_is_dropped_when_a_newer_one_has_written(client, monkeypatch, clock):
    """After the pause a new download may start while the stalled one is still
    out. The first to write wins; the other brought the same screener, and is
    dropped rather than written over it."""
    stalled, newer = _funds(6), _funds(7, first=100)
    source = Source(stalled, newer).holding(1)
    monkeypatch.setattr(catalogue, "_fetch_overview", source)
    _ensure(client)
    assert source.asked.wait(5)

    clock.now = NOW + STALLED + PAUSE
    _ensure(client)
    _wait_until(lambda: _status(client)["rows"] == 7)
    source.release.set()
    _finish()

    assert source.calls == 2
    assert _status(client)["rows"] == 7
    found = client.get("/api/instruments/search", params={"q": "Fund 100"}).json()
    assert [m["isin"] for f in found["families"] for m in f["members"]] == ["IE0000000100"]


# --- what the chat is told -----------------------------------------------------------


def test_the_chat_is_told_why_the_registry_is_empty_in_plain_words(client, monkeypatch, clock):
    """On 2026-10-02 a model handed only the fields told the reader "0 righe"
    and "fetched_at: null". The result now says where the download stands, in
    words the reader can be told, and sends no card after it."""

    def reading() -> str:
        with SessionLocal() as db:
            out = tools.invoke(db, _call("search_catalogue", query="world small cap"))
        assert out["ok"] is True and out["result"]["families"] == []
        said = " ".join(out["result"]["reading"])
        assert "plain words" in said and "offer no card" in said
        assert "instrument picker" not in said
        return said

    assert "reloading the page starts it" in reading()

    source = Source(ConnectionError("down"), _funds(6)).holding(2)
    monkeypatch.setattr(catalogue, "_fetch_overview", source)
    _ensure(client)
    _finish()
    clock.now = NOW + datetime.timedelta(minutes=3)
    failed = reading()
    assert "tried to download the list of funds from justETF and could not" in failed
    assert "in 7 minutes at the earliest" in failed
    clock.now = NOW + PAUSE
    assert "which a reload now will do" in reading()

    source.asked.clear()
    _ensure(client)
    assert source.asked.wait(5)
    assert "downloading the list of funds from justETF right now" in reading()
    source.release.set()
    _finish()


def test_a_card_asked_for_while_the_list_downloads_is_refused_with_where_it_stands(
    client, monkeypatch, clock
):
    """The card's refusal used to send the model to "the instrument picker",
    where a button no longer is."""
    source = Source(_funds(6)).holding(1)
    monkeypatch.setattr(catalogue, "_fetch_overview", source)
    _ensure(client)
    assert source.asked.wait(5)

    with SessionLocal() as db:
        out = tools.answer(
            db,
            _call(
                "suggest_instrument", isin="IE0000000001", reason="r", based_on="b",
                unknowns="u",
            ),
        )
    source.release.set()
    _finish()

    assert out["ok"] is False
    assert "registry is empty" in out["error"] and "downloading" in out["error"]
    assert "instrument picker" not in out["error"]


def test_the_prompt_reads_unasked_and_stands_advice_on_the_analysis():
    """The reader, 2026-10-03: "deve fare tutto da solo, se gli chiedo
    consigli". The read tools need no permission; a past statement is not
    called invented because its lookup is not shown; and advice is the third
    occasion for the analysis, always behind its card."""
    prompt = chat.SYSTEM_PROMPT
    assert "Reading needs no permission" in prompt
    assert "never ask whether to run one: run it" in prompt
    assert "Ask only before writing their records (a card) or spending their money" in prompt
    assert "never call a past statement invented" in prompt
    assert "when they ask for advice, which stands on it" in prompt
    assert "Never run one without its card: it costs money" in prompt
    assert "not free" not in prompt, "the look-through costs seconds, not money"
