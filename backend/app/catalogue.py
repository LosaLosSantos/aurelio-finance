"""A local registry of instruments, searched offline, so identity is CHOSEN.

Why this exists is not typos. Eight fields are typed by hand for every
position, and the ones nobody fills switch features off in silence: 22 of 25
positions carry no ISIN — the key the look-through hands to the issuer — and
until they were entered one by one, 23 collected no dividends because
`distribution_policy` was empty. Nothing was broken; the data never arrived.

Two rules shape everything here.

SEARCH IS LOCAL. The catalogue is answered from SQLite, so the picker works
with no network, instantly, and a slow or dead source can never block typing.
justETF has no timeout of its own (21 s on a dead network), which is precisely
why it must not sit on the hot path. The download is the app's own, in the
background, and nobody asks for it: see `ensure`.

IDENTITY IS NOT A QUOTATION. This file answers "what is this fund" — ISIN, full
name, accumulating or distributing. It never answers "what does it cost", and
two of its columns are actively dangerous if confused for that:

  * `share_class_currency` says USD for VWCE, which quotes in EUR in Milan.
    Filling a holding's currency from it recreates the phantom 17% gain
    documented in analytics.py.
  * `base_ticker` is not a Yahoo symbol. The catalogue gives one code per fund
    (EUNL for iShares Core MSCI World), and a holding is priced by the symbol
    of the listing it trades on: the same fund, a different listing.

So a pick fills name, ISIN and policy, and leaves the symbol alone.
"""

from __future__ import annotations

import datetime
import logging
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.database import SessionLocal, sole_writer

# The download happens with nobody watching, so what it did is said where the
# reader's problems show up: uvicorn's own logger, as `database.py` does.
_console = logging.getLogger("uvicorn.error")

SOURCE = "justetf"
# Where the refresh timestamp and row count live. `settings` is already a
# key->value table, so this needs no schema of its own.
META_FETCHED_AT = "catalogue_fetched_at"
META_ROWS = "catalogue_rows"

_POLICY = {"accumulating": "acc", "distributing": "dist"}

# Everything that distinguishes the twins rather than the fund. A quarter of
# the registry arrives in pairs — 1,124 of 4,544 rows share a name with a
# sibling and differ only in what they do with dividends, across 560 families
# — so the family key strips exactly these and nothing else. The counts move
# with every refresh, so the query that produced them travels with them:
#   select count(*) from instruments where family_key in (select family_key
#     from instruments group by family_key having count(*) > 1)
# 1124 of 4544 on 2026-09-04. The share is the durable fact and the two
# numbers are only its evidence — the previous pair sat here across a refresh
# that had already moved them, which is what a figure with no query does.
_TWIN_MARKERS = re.compile(
    r"\b(acc|accumulating|dist|distributing|inc|income|thesaurierend|ausschüttend)\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)


def family_key(name: str) -> str:
    """The fund, with the accumulating/distributing distinction removed.

    Two rows that differ only in what they do with dividends are the SAME
    choice presented twice (iShares Core MSCI World's IWDD, Dist, and EUNL,
    Acc, carry identical names), so a result list that shows one of them alone
    invites picking the wrong one without ever revealing there was a pair."""
    cleaned = _TWIN_MARKERS.sub(" ", name or "")
    cleaned = _PUNCT.sub(" ", cleaned).lower()
    return " ".join(cleaned.split())


def _fetch_overview():
    """The justETF screener as a DataFrame indexed by ISIN. Network call."""
    import justetf_scraping

    return justetf_scraping.load_overview()


def _clean(value) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _number(value):
    """Pandas NA-safe scalar, or None."""
    try:
        if value is None or value != value:  # NaN
            return None
        return value.item() if hasattr(value, "item") else value
    except Exception:
        return None



def _ensure_fts(db: Session) -> None:
    """The search index, created on demand.

    The regular table is an ORM model, so it exists wherever the schema does.
    A virtual table is not something SQLAlchemy builds, so it is created here
    instead of only in the migration — which also means a database that
    predates this feature heals itself on first use rather than raising."""
    db.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS instruments_fts USING fts5("
            "isin UNINDEXED, name, base_ticker, tokenize='unicode61')"
        )
    )


# --- The download: the app's own, and nobody asks for it ---------------------
#
# Every page load asks (`ensure`, posted from App.tsx beside the ledger
# catch-up) and the answer is decided here: a download starts only when the
# catalogue is DUE and none is running, on a thread of its own, and the page is
# answered at once. Due means empty, undated, or a week old. Funds launch and
# close every month, so a month would leave a closed fund suggestible for weeks,
# and a day would download at almost every opening for data that moves monthly.
# Measured 2026-10-04 against the copy of 2026-09-04: 6 of its 4,544 funds had
# left, and 74 had arrived.
#
# Asked by the page and not at the backend's start, for three reasons. Offline
# at the opening heals at the next reload, not at the next restart of the
# server; the age is looked at whenever the app is opened, not once per
# process; and a test client, whose start runs in hundreds of tests, starts no
# download.
#
# One at a time, guarded IN THIS PROCESS, because every trigger comes through
# it: the MCP server reads the same file and cannot write. Not SQLite's write
# lock, which is never held across the network (`database.sole_writer`). A
# second download would be wasted traffic, not wrong data, since the table is
# replaced whole in one transaction; the guard is about asking justETF once.
MAX_AGE = datetime.timedelta(days=7)
# justETF's four requests carry no timeout (read in justetf_scraping), so a
# download that hangs would say "downloading" for ever. The real one took 7.2 s
# on 2026-10-04; one still running after this has failed, whatever it does
# later (`_download` says what happens if it finishes).
STALLED_AFTER = datetime.timedelta(minutes=5)
# After a failure the next page load waits this long before asking again, so
# reloads cannot hammer a source that answers badly: six tries an hour at most,
# and a wait a reader can sit out.
PAUSE_AFTER_FAILURE = datetime.timedelta(minutes=10)
# A download much smaller than the catalogue it would replace is a broken one,
# not a market that shrank. justETF listed 4,612 funds on 2026-10-04: 3,770
# Long-only, 696 Active and 146 Short & Leveraged, each type asked for in its
# own request; and in the month before, 6 of 4,544 had left. Under nine tenths
# of what is stored, a download has lost a whole type (Active alone leaves
# 84.9%) or been cut short. Losing the smallest type leaves 96.8%, too close to
# the churn for a floor, so each type is also checked by name (`_check_types`).
SHRINK_FLOOR = 0.9
# The floor and the type check protect a catalogue of justETF's size. A
# registry under this is not one (empty, the suite's three-fund catalogues, a
# partial copy): any list justETF sends beats it, and in a three-fund registry
# one fund leaving the market is a third of it.
FULL_CATALOGUE = 1_000
THREAD_NAME = "aurelio-catalogue-download"


class Busy(RuntimeError):
    """A download is already running, so this one was not started."""


class Refused(RuntimeError):
    """justETF answered, and what it sent is not a catalogue to keep. The
    stored one stays exactly as it was."""


@dataclass
class _Attempt:
    """One download, from the moment a caller claimed it."""

    started: datetime.datetime
    ended: datetime.datetime | None = None
    failure: str | None = None

    def running(self, now: datetime.datetime) -> bool:
        return self.ended is None and now - self.started < STALLED_AFTER

    def failed_at(self, now: datetime.datetime) -> datetime.datetime | None:
        """When it failed, or None. One still running past STALLED_AFTER
        failed then."""
        if self.ended is not None:
            return self.ended if self.failure else None
        if now - self.started >= STALLED_AFTER:
            return self.started + STALLED_AFTER
        return None


# The last download claimed in this process. The lock guards it for a few reads
# and assignments, and is never held across the network.
_guard = threading.Lock()
_last: _Attempt | None = None


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(moment: datetime.datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _count(db: Session) -> int:
    return db.execute(text("SELECT count(*) FROM instruments")).scalar() or 0


def _due(db: Session, now: datetime.datetime) -> bool:
    """Empty, undated, or a week old."""
    if not _count(db):
        return True
    try:
        fetched = datetime.datetime.fromisoformat(_get_meta(db, META_FETCHED_AT))
        return now - fetched >= MAX_AGE
    except (TypeError, ValueError):  # no date, or one that is not a date
        return True


def _claim(db: Session, *, forced: bool) -> _Attempt | None:
    """The next download, if this caller is the one to start it: None while
    one is running and, unless forced, within PAUSE_AFTER_FAILURE of a failure
    or when nothing is due. Decided under the lock, so of two callers at once
    exactly one gets it."""
    global _last
    now = _now()
    with _guard:
        last = _last
        if last is not None and last.running(now):
            return None
        if not forced:
            failed = last.failed_at(now) if last is not None else None
            if failed is not None and now < failed + PAUSE_AFTER_FAILURE:
                return None
            if not _due(db, now):
                return None
        _last = _Attempt(started=now)
        return _last


def _end(attempt: _Attempt, failure: str | None = None) -> None:
    with _guard:
        attempt.ended = _now()
        attempt.failure = failure


def _forget() -> None:
    """Back to a process that has tried nothing (the suite, between tests)."""
    global _last
    with _guard:
        _last = None


def _reason(exc: Exception) -> str:
    if isinstance(exc, Refused):
        return str(exc)
    first = (str(exc).strip().splitlines() or [""])[0]
    return f"{type(exc).__name__}: {first}"[:300]


def ensure(db: Session) -> dict:
    """Start a download in the background when one is due, and say where the
    catalogue stands. Answers at once: nothing here waits on justETF."""
    attempt = _claim(db, forced=False)
    if attempt is not None:
        threading.Thread(
            target=_download_in_background, args=(attempt,), name=THREAD_NAME, daemon=True
        ).start()
    return status(db)


def refresh(db: Session) -> dict:
    """Download now and wait for it, whatever the catalogue's age: the door for
    a download by hand, and how the suite loads a fake catalogue. Still one at
    a time (`Busy`), and its failure is recorded like any other."""
    attempt = _claim(db, forced=True)
    if attempt is None:
        raise Busy("A download of the fund catalogue is already running.")
    try:
        done = _download(db, attempt)
    except Exception as exc:
        _end(attempt, _reason(exc))
        raise
    _end(attempt)
    return done


def _download_in_background(attempt: _Attempt) -> None:
    """The download on its own thread and its own session: the request that
    started it has long been answered."""
    db = SessionLocal()
    try:
        _download(db, attempt)
    except Exception as exc:
        reason = _reason(exc)
        _end(attempt, reason)
        _console.warning(
            "The fund catalogue could not be downloaded from justETF (%s). The app "
            "tries again when it is next opened, %d minutes from now at the earliest.",
            reason,
            PAUSE_AFTER_FAILURE.total_seconds() // 60,
        )
    else:
        _end(attempt)
    finally:
        db.close()


def _rows(df, fetched_at: str) -> list[dict]:
    """The screener's funds as `instruments` rows; one with no ISIN or no name
    is not a fund anybody could pick."""
    rows = []
    for isin, r in df.iterrows():
        name = _clean(r.get("name"))
        if not isin or not name:
            continue
        rows.append(
            {
                "isin": str(isin).strip().upper(),
                "name": name,
                "family_key": family_key(name),
                "base_ticker": _clean(r.get("ticker")),
                "distribution_policy": _POLICY.get(
                    str(r.get("dividends") or "").strip().lower()
                ),
                "ter": _number(r.get("ter")),
                "size_meur": _number(r.get("size")),
                "replication": _clean(r.get("replication")),
                "domicile": _clean(r.get("domicile_country")),
                "share_class_currency": _clean(r.get("currency")),
                "holdings_count": _number(r.get("number_of_holdings")),
                "hedged": bool(r.get("hedged")) if r.get("hedged") is not None else None,
                "source": SOURCE,
                "fetched_at": fetched_at,
            }
        )
    return rows


def _check_types(df) -> None:
    """Every fund type justETF lists has to come back with funds in it.

    The library asks for each type in its own request and labels every fund
    with its type in a `strategy` column. A request answered with an empty list
    raises nothing, so a type can vanish in silence; the smallest, 146 funds of
    4,612 on 2026-10-04, is too small for the floor to notice. A source with no
    such column (the suite's small catalogues) has nothing to check."""
    if "strategy" not in getattr(df, "columns", ()):
        return
    from justetf_scraping.helpers import STRATEGIES

    labels = df["strategy"].astype(str)
    missing = [t for t in STRATEGIES.values() if not labels.str.contains(t, regex=False).any()]
    if missing:
        raise Refused("justETF sent no " + " and no ".join(missing) + " funds")


def _later(stamp: str | None, moment: datetime.datetime) -> bool:
    try:
        return datetime.datetime.fromisoformat(stamp) > moment
    except (TypeError, ValueError):
        return False


def _download(db: Session, attempt: _Attempt) -> dict:
    """Fetch, check, then replace what is stored.

    Replaced wholesale rather than merged: the source is a full screener export,
    so a fund that has left it has left the market, and keeping it would be
    inventing a listing that no longer exists. The network is asked holding
    nothing; SQLite's write lock is taken only to check again and write (0.05
    to 0.09 s for 4,612 funds, measured 2026-10-04).

    A download that finishes after STALLED_AFTER, already reported as failed,
    still writes: what it brought is a whole screener, and discarding it would
    fail every attempt on a connection that is slow but working. Unless the
    catalogue was written after this download started: another one finished
    meanwhile, with the same screener a little later, and this one is dropped.
    """
    df = _fetch_overview()
    fetched_at = _stamp(_now())
    rows = _rows(df, fetched_at)
    if not rows:
        raise Refused("justETF sent no funds")
    with sole_writer(db):
        _ensure_fts(db)
        if _later(_get_meta(db, META_FETCHED_AT), attempt.started):
            return {"rows": _count(db), "fetched_at": _get_meta(db, META_FETCHED_AT)}
        stored = _count(db)
        if stored >= FULL_CATALOGUE:
            if len(rows) < SHRINK_FLOOR * stored:
                raise Refused(f"justETF sent {len(rows)} funds where {stored} are stored")
            _check_types(df)
        db.execute(text("DELETE FROM instruments"))
        db.execute(text("DELETE FROM instruments_fts"))
        db.execute(
            text(
                "INSERT INTO instruments (isin, name, family_key, base_ticker,"
                " distribution_policy, ter, size_meur, replication, domicile,"
                " share_class_currency, holdings_count, hedged, source, fetched_at)"
                " VALUES (:isin, :name, :family_key, :base_ticker,"
                " :distribution_policy, :ter, :size_meur, :replication, :domicile,"
                " :share_class_currency, :holdings_count, :hedged, :source, :fetched_at)"
            ),
            rows,
        )
        db.execute(
            text(
                "INSERT INTO instruments_fts (isin, name, base_ticker)"
                " VALUES (:isin, :name, :base_ticker)"
            ),
            [{"isin": r["isin"], "name": r["name"], "base_ticker": r["base_ticker"]} for r in rows],
        )
        _set_meta(db, META_FETCHED_AT, fetched_at)
        _set_meta(db, META_ROWS, str(len(rows)))
    _console.info("Fund catalogue downloaded from justETF: %d funds.", len(rows))
    return {"rows": len(rows), "fetched_at": fetched_at}


def _set_meta(db: Session, key: str, value: str) -> None:
    db.execute(
        text(
            "INSERT INTO settings (key, value) VALUES (:k, :v)"
            " ON CONFLICT(key) DO UPDATE SET value = :v"
        ),
        {"k": key, "v": value},
    )


def _get_meta(db: Session, key: str) -> str | None:
    row = db.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key}).first()
    return row[0] if row else None


def status(db: Session) -> dict:
    """What the registry holds, how old it is, and where its download stands,
    in this process: shown, never assumed.

    `state` is "downloading"; "failed", tried again at a page load from
    `retry_after` on; "ready"; or "not_started", for an empty registry nobody
    has asked about since the server started."""
    rows = _count(db)
    now = _now()
    with _guard:
        last = _last
        running = last is not None and last.running(now)
        failed = None if last is None or running else last.failed_at(now)
    if running:
        state, retry_after = "downloading", None
    elif failed is not None:
        state, retry_after = "failed", _stamp(failed + PAUSE_AFTER_FAILURE)
    else:
        state, retry_after = ("ready" if rows else "not_started"), None
    return {
        "rows": rows,
        "fetched_at": _get_meta(db, META_FETCHED_AT),
        "source": SOURCE,
        "state": state,
        "retry_after": retry_after,
    }


def facts(db: Session, isins: Iterable[str]) -> dict:
    """What the registry says about the funds a person holds, for the contexts
    the chat and the analysis read: each fund's ongoing charge and the facts
    that qualify it, keyed by ISIN, beside how many funds the registry holds
    and when it was downloaded.

    Run 2 of the analysis, on 2026-10-03, quoted four funds' charges from the
    model's memory, "VWCE ~0.22%" among them, while the copy of this registry
    downloaded on 2026-09-04 gave that fund 0.14.

    An ISIN is looked up as the registry stores it, trimmed and upper case;
    a holding keeps it as it was typed. One the registry does not hold is
    absent from `funds`, and `rows` says whether that is because the registry
    is empty. Read only: nothing here downloads."""
    wanted = sorted({isin.strip().upper() for isin in isins if isin and isin.strip()})
    funds: dict[str, dict] = {}
    if wanted:
        found = db.execute(
            text(
                "SELECT isin, ter, distribution_policy, domicile, replication, hedged,"
                " size_meur FROM instruments WHERE isin IN :isins"
            ).bindparams(bindparam("isins", expanding=True)),
            {"isins": wanted},
        ).mappings().all()
        funds = {row["isin"]: dict(row) for row in found}
    return {"rows": _count(db), "fetched_at": _get_meta(db, META_FETCHED_AT), "funds": funds}


_TOKEN = re.compile(r"[\w]+", re.UNICODE)


def _tokens(query: str) -> list[str]:
    """Words, with the punctuation FTS5 would read as syntax removed.

    Passing input straight through is not an option: `MATCH 'Vanguard FTSE
    All-World'` raises `no such column: World`, because the hyphen makes FTS5
    parse the tail as a column expression. Every token is quoted instead."""
    return [t for t in _TOKEN.findall(query or "") if t]


def search(db: Session, query: str, limit: int = 8) -> dict:
    """Families of instruments matching `query`, from the local registry only.

    Returns families rather than rows so the Acc/Dist twins always travel
    together. `coverage` says how the match was made: "all" means every word
    was found, "partial" means the search had to loosen to find anything — a
    distinction the caller is expected to show, since a loosened match is a
    weaker claim about what you asked for."""
    _ensure_fts(db)
    words = _tokens(query)
    # One character matches thousands of rows and means nothing; the list would
    # be noise pretending to be a shortlist.
    if not words or len("".join(words)) < 2:
        return {"families": [], "coverage": "none", **status(db)}

    quoted_all = " AND ".join(f'"{w}"' for w in words)
    matched = _match(db, quoted_all, limit * 4)
    coverage = "all"
    if not matched:
        # Prefix on the last word, OR across the rest: finds something while
        # still typing, and says that it did so. The asterisk goes OUTSIDE the
        # quotes — inside them FTS5 reads it as a literal character, which is
        # why "vangu*" matched nothing at all.
        loose = " OR ".join(
            [f'"{w}"' for w in words[:-1]] + [f'"{words[-1]}" *'.replace('" *', '"*')]
        )
        matched = _match(db, loose, limit * 4)
        coverage = "partial" if matched else "none"
    if not matched:
        return {"families": [], "coverage": "none", **status(db)}

    keys = list(dict.fromkeys(m for m in matched))  # order preserved
    families = _families(db, keys[: limit * 2], limit)
    return {"families": families, "coverage": coverage, **status(db)}


def _match(db: Session, expression: str, limit: int) -> list[str]:
    """Family keys of the rows FTS5 matched, best first."""
    rows = db.execute(
        text(
            "SELECT i.family_key FROM instruments_fts f"
            " JOIN instruments i ON i.isin = f.isin"
            " WHERE instruments_fts MATCH :q"
            " ORDER BY rank LIMIT :n"
        ),
        {"q": expression, "n": limit},
    ).all()
    return [r[0] for r in rows]


def _families(db: Session, keys: list[str], limit: int) -> list[dict]:
    """Every member of each matched family, so a twin is never shown alone."""
    out: list[dict] = []
    for key in keys[:limit]:
        rows = db.execute(
            text(
                "SELECT isin, name, base_ticker, distribution_policy, ter,"
                " size_meur, replication, domicile, share_class_currency,"
                " holdings_count, hedged"
                " FROM instruments WHERE family_key = :k"
                " ORDER BY distribution_policy IS NULL, distribution_policy, name"
            ),
            {"k": key},
        ).mappings().all()
        if not rows:
            continue
        out.append({"key": key, "members": [dict(r) for r in rows]})
    return out
