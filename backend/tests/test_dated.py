"""The anchor rule, asserted once instead of in five places.

Every projection in this app is `anchor + events strictly after it`. That rule
had five different spellings before `app.dated` — two open-ended, two half-open
intervals, one with a different variable name for the same idea — and each had
to get the strictness right on its own. These tests are what makes the
docstring in `events_after` a promise rather than a comment.
"""

from __future__ import annotations

import datetime

import pytest

from app import dated


class _Rec:
    """The shape both a mapped row and a `(date, value)` pair reduce to."""

    def __init__(self, date: str, tag: str) -> None:
        self.date, self.tag = date, tag

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<{self.tag} {self.date}>"


ROWS = [_Rec("2026-01-01", "a"), _Rec("2026-03-01", "b"), _Rec("2026-06-01", "c")]


def test_the_anchors_own_date_is_already_in_the_photograph():
    """The invariant. A photograph taken on the 1st contains everything that
    had happened by the end of the 1st, so an entry dated the 1st must NOT be
    applied on top of it — that is the same money counted twice."""
    anchor = _Rec("2026-03-01", "anchor")
    assert [r.tag for r in dated.events_after(anchor, ROWS)] == ["c"]


def test_until_is_inclusive_because_a_day_is_over_when_it_ends():
    """The other boundary: a series point for the 1st shows what the 1st looked
    like when it ended, so a sale that day has happened by then."""
    got = dated.events_after(_Rec("2026-01-01", "anchor"), ROWS, until="2026-03-01")
    assert [r.tag for r in got] == ["b"]


def test_no_anchor_leaves_every_event_outstanding():
    """Nothing has been photographed yet, so nothing is already accounted for."""
    assert len(dated.events_after(None, ROWS)) == 3


def test_an_anchor_may_be_a_row_or_a_bare_date():
    assert dated.events_after("2026-03-01", ROWS) == dated.events_after(ROWS[1], ROWS)


def test_the_record_in_force_is_the_latest_on_or_before():
    """Inclusive, and complementary to `events_after`: what the anchor covers
    ends on its own date, and what is outstanding starts strictly after it, so
    nothing is counted twice and nothing falls between them."""
    assert dated.latest_on_or_before(ROWS, "2026-03-01").tag == "b"
    assert dated.latest_on_or_before(ROWS, "2026-02-28").tag == "a"
    assert dated.latest_on_or_before(ROWS, "2025-12-31") is None


def test_carry_forward_sums_what_was_in_force_and_ignores_what_had_not_started():
    """A valuation stands until a newer one replaces it; a house bought next
    year is not worth its price today."""
    series = {
        1: [("2026-01-01", 100.0), ("2026-06-01", 150.0)],
        2: [("2026-04-01", 40.0)],
    }
    assert dated.carry_forward(series, "2026-01-01") == 100.0
    assert dated.carry_forward(series, "2026-05-01") == 140.0
    assert dated.carry_forward(series, "2026-06-01") == 190.0
    assert dated.carry_forward(series, "2025-01-01") == 0.0


def test_latest_per_parent_of_keeps_one_row_per_parent():
    rows = [_Rec("2026-01-01", "a"), _Rec("2026-03-01", "b")]
    rows[0].parent = rows[1].parent = 7
    latest = dated.latest_per_parent_of(
        rows, lambda r: r.parent, on_or_before="2026-06-01"
    )
    assert latest[7].tag == "b"
    assert dated.latest_per_parent_of(
        rows, lambda r: r.parent, on_or_before="2026-02-01"
    )[7].tag == "a"


def test_the_latest_in_force_cannot_be_asked_without_a_date():
    """The defect this module now makes unwriteable: "the latest row there is"
    is a different question from "the latest row in force", and every caller
    wanted the second one while asking the first. There is no longer a way to
    ask the first — the bound is required, so a caller that means today has to
    say so."""
    rows = [_Rec("2026-01-01", "a")]
    rows[0].parent = 7
    with pytest.raises(TypeError):
        dated.latest_per_parent_of(rows, lambda r: r.parent)


def test_today_is_the_bound_a_caller_meaning_now_passes():
    assert dated.today() == datetime.date.today().isoformat()
