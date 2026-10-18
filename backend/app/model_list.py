"""OpenRouter's public list of models, read once a day (brief BB).

The list (`advisor.MODEL_LIST_URL`) dates some models for removal: on
2026-10-17, 17 of its 470 entries carried an `expiration_date`, 3 to 75 days
ahead, which its API reference calls "the date after which the model may be
removed". Until brief BB the app read the list only after OpenRouter had
refused a call (`advisor._refused`, `2ba7466`), so a model was said only once a
call to it had failed. Read ahead, the same list lets the chat's menu say a
model's date beside its name, and the app say a model it is about to use,
wherever that model is set, before a call to it fails (`warning`).

What is asked: one request for the whole list, with nothing in it of the
reader's: no key, no query, no body, httpx's own headers and nothing else. So
OpenRouter learns that this address asked for its list, as it learns this
address whenever the chat asks a question, and nothing more. Never a lookup of
one model, which would say which models the reader uses. Without an
`OPENROUTER_API_KEY` no model can be called at all, and nothing is asked.

How often: at most once a reader's day (`dated.today()`). The day is claimed in
`settings` before the request, so a second tab, React's second effect or a
restart the same day asks nothing more; the read that comes back is kept there
and in memory, and used on its own day only. It is asked in the background, on
a thread with a session of its own as the catalogue's download is: at startup,
and by the first request that reads it on a new day. Nothing waits for it, so
no page does. Until it is back, on a day it failed, or offline, nothing is said
anywhere, as before this module, and the next day asks again.

After a refusal, `advisor._refused` still asks the list as it is then
(`read_now`), and what that read finds becomes the day's copy, so the menu says
what the reader was just told (the reader's choice, 2026-10-17).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from dataclasses import dataclass

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import advisor, dated, models, websearch
from app.database import SessionLocal, sole_writer

_log = logging.getLogger(__name__)

# Where the day is kept, in `settings`: the reader's day the list was last
# asked, and the last read that came back, with the day it was read.
ASKED_ON = "model_list_asked_on"
KEPT = "model_list"
THREAD_NAME = "aurelio-model-list"


@dataclass(frozen=True)
class Listing:
    """OpenRouter's list as read on `day`: every id it has, each with the day
    after which it may be removed, or None when it gives none."""

    day: str
    dates: dict[str, str | None]

    def has(self, model: str) -> bool:
        """Whether the list has the entry that describes `model`: its base and
        its catalog variant, as OpenRouter resolves a name (`advisor.catalog_id`)."""
        return advisor.catalog_id(model) in self.dates

    def retires(self, model: str) -> str | None:
        """The day the list gives `model`'s entry, or None."""
        return self.dates.get(advisor.catalog_id(model))


def _listing(day: str, dates: dict) -> Listing:
    """A read as kept: every id, and its date only when it is one. The reference
    promises "YYYY-MM-DD or null"; anything else is kept as no date, since a
    figure the app cannot read is not one to warn about."""
    return Listing(day=day, dates={str(model): _a_day(when) for model, when in dates.items()})


def _a_day(value) -> str | None:
    try:
        return datetime.date.fromisoformat(str(value)).isoformat() if value else None
    except ValueError:
        return None


# --- Said before a call -----------------------------------------------------------

# How long before the day the list gives a model it is said where that model is
# about to be used: the line above the chat's question box and the band on the
# analysis's card (the reader's choice, 2026-10-17, as the reviewer advised).
# The menu shows the date from the first day; the line waits until the day is
# this close, so that it does not sit in the chat for two months over a model
# the reader may leave anyway. On 2026-10-17 the list's 17 dates lay 3 to 75
# days ahead, half of them within 14: this held back 2, both dated 2026-12-31,
# until 2026-12-01. A day already past, or a model the list lacks, is said
# whatever the day.
WARN_DAYS = 30

# Where a model is set, and how it is changed, for one still to be used.
SET_IN_ENV = (
    "It is set by {names} in backend/.env, where another model takes its place "
    "once the app starts again."
)
BUILT_IN = (
    "It is the app's built-in default (DEFAULT_MODEL in backend/app/advisor.py); "
    "OPENROUTER_MODEL in backend/.env sets another once the app starts again."
)
PICKED = "It is picked in the menu under the question, where another can be picked."
SEARCH_SET = "It is set in the app's code (SEARCH_MODEL in backend/app/websearch.py)."


def where_set(model: str, *uses: tuple[str, ...]) -> str:
    """Where the reader changes `model` for the uses that take it. Each use
    reads its variables in backend/.env in order, before the app's own default
    (the chat's when nothing is picked, `chat.DEFAULT_READS`; a role's of the
    analysis, `chain.ROLE_READS`), and takes the first of them that is set,
    else the built-in default. Every variable in force for `model` is named,
    and the built-in default when a use takes it; a model no use takes is a
    pick from the chat's menu.

    `advisor._where_set` says it after a refusal by every variable that names
    the model; before a call it is said for the use about to happen, since a
    variable another use reads does not change this one."""
    named: list[str] = []
    built_in = False
    for reads in uses:
        in_force = next((var for var in reads if os.getenv(var)), None)
        if in_force is None:
            built_in = built_in or model == advisor.DEFAULT_MODEL
        elif os.getenv(in_force) == model and in_force not in named:
            named.append(in_force)
    said = [SET_IN_ENV.format(names=advisor._and(named))] if named else []
    if built_in:
        said.append(BUILT_IN)
    return " ".join(said) or PICKED


def warning(model: str, listing: Listing | None, where: str) -> str | None:
    """What is said of `model` where it is about to be used, or None: what the
    day's list says of it, when that is to be said today (`_said`); where it is
    set and how to change it (`where`); and, for a model the list lacks, the
    dated versions of it the list still has. OpenRouter names nothing in a
    dated model's place (brief BB's P0, 2026-10-17), so nothing is said there."""
    said = _said(model, listing, search=False)
    if said is None:
        return None
    versions = "" if listing.has(model) else advisor.still_listed(advisor.catalog_id(model), listing.dates)
    return f"{said} {where}{versions}"


def search_warning(listing: Listing | None) -> str | None:
    """What is said of the web search's model (`websearch.SEARCH_MODEL`) where
    a model that searches is about to be used, or None."""
    model = websearch.SEARCH_MODEL
    said = _said(model, listing, search=True)
    if said is None:
        return None
    versions = "" if listing.has(model) else advisor.still_listed(advisor.catalog_id(model), listing.dates)
    return f"{said} {SEARCH_SET}{versions}"


def _said(model: str, listing: Listing | None, *, search: bool) -> str | None:
    """What the day's list says of `model`, when it is to be said today: a
    model it lacks, a day already past, or a day within WARN_DAYS. None when
    there is no list today, or nothing to say. `search` says it of the model
    the web searches run on. "No longer listed", not "gone": a name that had
    left the list was seen still answering (2026-09-24), so an absence alone
    is not proof (the reader's words, 2026-10-17)."""
    if listing is None:
        return None
    if not listing.has(model):
        if search:
            return (
                f"The web searches run on {model}, which OpenRouter's list of models no "
                "longer has, so a search may be refused."
            )
        return f"OpenRouter's list of models no longer has {model}, so a call to it may be refused."
    day = listing.retires(model)
    if day is None:
        return None
    left = (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(dated.today())).days
    if left < 0:
        if search:
            return (
                f"The web searches run on {model}, which OpenRouter's list of models dated "
                f"for removal after {day}, so it may stop serving it at any time."
            )
        return (
            f"OpenRouter's list of models dated {model} for removal after {day}, so it "
            "may stop serving it at any time."
        )
    if left <= WARN_DAYS:
        if search:
            return f"The web searches run on {model}, which OpenRouter may retire after {day}."
        return f"OpenRouter may retire {model} after {day}, the date its list of models gives."
    return None


# What this process knows. The lock guards a few reads and assignments and is
# never held across the network or the database.
_guard = threading.Lock()
_kept: Listing | None = None
# The day this process last started a read, or found one already kept: no
# second thread is started for it.
_tried_on: str | None = None


def known(db: Session) -> Listing | None:
    """Today's read of the list, or None: before the day's read is back, on a
    day it failed, without a key. Starts the day's read when it is due and
    never waits for it."""
    day = dated.today()
    with _guard:
        kept = _kept
    if kept is not None and kept.day == day:
        return kept
    stored = _stored(db)
    if stored is not None and stored.day == day:
        _keep(stored)
        return stored
    start_if_due()
    return None


def start_if_due() -> None:
    """Start the day's read on a thread of its own, unless this process has
    already started one today, or found one kept, or there is no key to call a
    model with. Returns at once."""
    global _tried_on
    if not os.getenv("OPENROUTER_API_KEY"):
        return
    day = dated.today()
    with _guard:
        if _tried_on == day:
            return
        _tried_on = day
    threading.Thread(target=_read_in_background, args=(day,), name=THREAD_NAME, daemon=True).start()


def read_now() -> dict[str, str | None]:
    """The list as OpenRouter has it now, asked at once, after it refused a
    call (`advisor._refused`). What comes back is the day's read from then on:
    in memory at once, and in `settings` from a thread of its own, so the
    caller, which may be holding a write of its own, waits for nothing. Raises
    whatever the request raised."""
    listing = _listing(dated.today(), advisor._fetch_model_list())
    _keep(listing)
    threading.Thread(target=_store_in_background, args=(listing,), name=THREAD_NAME, daemon=True).start()
    return listing.dates


def _read_in_background(day: str) -> None:
    """The day's read, on its own session: claim the day, ask, keep what came
    back. Whatever goes wrong ends it and is said nowhere (an outage leaves the
    app as it was before this module); the next day asks again."""
    db = SessionLocal()
    try:
        with sole_writer(db):
            claimed = _value(db, ASKED_ON) != day
            if claimed:
                _put(db, ASKED_ON, day)
        if not claimed:
            # Asked already today, before a restart or by another process:
            # what came back then, if anything did, is the day's.
            stored = _stored(db)
            if stored is not None and stored.day == day:
                _keep(stored)
            return
        listing = _listing(day, advisor._fetch_model_list())
        with sole_writer(db):
            _put(db, KEPT, _dumped(listing))
        _keep(listing)
    except Exception as exc:
        _log.debug("OpenRouter's list of models was not read on %s: %s", day, exc)
    finally:
        db.close()


def _store_in_background(listing: Listing) -> None:
    """Keep a read made after a refusal as the day's, in `settings`."""
    db = SessionLocal()
    try:
        with sole_writer(db):
            _put(db, ASKED_ON, listing.day)
            _put(db, KEPT, _dumped(listing))
    except Exception as exc:
        _log.debug("OpenRouter's list of models, read after a refusal, was not kept: %s", exc)
    finally:
        db.close()


def _keep(listing: Listing) -> None:
    global _kept, _tried_on
    with _guard:
        _kept = listing
        _tried_on = listing.day


def _forget() -> None:
    """Back to a process that has read nothing (the suite, between tests)."""
    global _kept, _tried_on
    with _guard:
        _kept = _tried_on = None


def _dumped(listing: Listing) -> str:
    return json.dumps({"day": listing.day, "models": listing.dates}, separators=(",", ":"))


def _stored(db: Session) -> Listing | None:
    """The read kept in `settings`, or None when there is none or it cannot be
    read back."""
    raw = _value(db, KEPT)
    try:
        kept = json.loads(raw) if raw else None
        return _listing(str(kept["day"]), dict(kept["models"])) if kept else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def _value(db: Session, key: str) -> str | None:
    row = db.get(models.Setting, key)
    return row.value if row is not None else None


def _put(db: Session, key: str, value: str) -> None:
    kept = sqlite_insert(models.Setting).values(key=key, value=value)
    db.execute(kept.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
