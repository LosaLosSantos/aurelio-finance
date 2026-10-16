"""Which dividend an entry of the ledger is: the window after each ex-date,
and the pairing of the reader's entries with the dividends Yahoo lists.

Brief AZ (2026-10-16). The catch-up records a dividend on its ex-date, while a
reader types it from the statement, dated the day the broker credited it,
days or weeks later. Typed before the catch-up reached the ex-date (a rate not
published yet, Yahoo not answering that day, the app not opened), it was
stored beside the row the catch-up then recorded, and the cash, the dividends
collected and the tax estimate counted both (measured at `eaa89fc`: 5.00
gross beside the 3.70 typed, the cash at 5,008.70 where 5,003.70 is right).
So before recording a dividend the catch-up looks for the reader's entry of it.

THE WINDOW is where a dividend's money can arrive: from its ex-date to
whichever is later, the next ex-date Yahoo lists or `REACH` after it. Yahoo
gives a payment date only for a US listing, and for one dividend at a time
(measured 2026-10-16 on 40 public tickers): 14 to 24 days after the ex-date on
seven US shares, 28 to 69 on five ADRs. Two of those ADRs pay monthly and their
ex-dates are 1 to 33 days apart, so each pays after its next one or two: a
window ending at the next ex-date would hand a credit to a later dividend, that
one taken as entered and the right one recorded again. Where ex-dates are 70
days and more apart (every quarterly, half-yearly and yearly payer measured),
the window is the period to the next one; for the latest listed, `REACH` or
the ticker's usual spacing, whichever is longer.

THE PAIRING is recognised only when it is unique both ways: the entry is the
only one in that dividend's window, and the dividend the only one whose window
holds the entry. Every other case is asked, and the app writes nothing until
the reader answers: never two rows for one dividend, and never an entry taken
for a dividend it is not, in silence. A dividend the app already recorded,
still at the market's estimate, is paired too: that is the double the two
defects left on record, asked about rather than resolved.

Pure: no database, no clock. `pac` reads the rows and writes the answers.
"""

from __future__ import annotations

import datetime
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field

# The longest payment lag measured, 69 days (an ADR's), rounded up: a window
# that ends before the money can arrive misses the reader's entry of it.
REACH = datetime.timedelta(days=70)
# The spacing taken for a ticker that has listed a single dividend: a year,
# the longest an annual payer's ex-dates were measured apart (364 days).
NO_SPACING = datetime.timedelta(days=365)


def windows(ex_dates: Iterable[str]) -> dict[str, tuple[str, str]]:
    """{ex-date: (its first day, the day after its last)} for every ex-date
    listed, ISO strings, the end exclusive."""
    days = sorted({datetime.date.fromisoformat(d) for d in ex_dates})
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    usual = datetime.timedelta(days=statistics.median(gaps)) if gaps else NO_SPACING
    out: dict[str, tuple[str, str]] = {}
    for i, day in enumerate(days):
        if i + 1 < len(days):
            end = max(days[i + 1], day + REACH)
        else:
            end = day + max(REACH, usual)
        out[day.isoformat()] = (day.isoformat(), end.isoformat())
    return out


def inside(day: str, window: tuple[str, str]) -> bool:
    """Whether `day` falls in `window`, its end excluded."""
    return window[0] <= day < window[1]


@dataclass(frozen=True)
class Dividend:
    """A dividend the catch-up may record or has recorded at its estimate:
    one an entry of the reader's can be. `estimate_id` is the app's row for
    it, still estimated, or None while nothing is recorded."""

    ex_date: str
    estimate_id: int | None = None


@dataclass
class Pairing:
    """What the catch-up does about one position's entries and dividends.

    `recognised`: (entry, ex-date) pairs, unique both ways, the dividend not
    recorded: the entry takes the ex-date and nothing is recorded.
    `doubles`: (entry, ex-date) pairs, unique both ways, the dividend already
    recorded at its estimate: asked whether they are one dividend.
    `by_dividend`: a dividend two or more entries could be: asked which.
    `by_entry`: an entry two or more dividends could be: asked which.
    `held`: every dividend some entry could be, which is not recorded now."""

    recognised: list[tuple[int, str]] = field(default_factory=list)
    doubles: list[tuple[int, str]] = field(default_factory=list)
    by_dividend: list[tuple[str, list[int]]] = field(default_factory=list)
    by_entry: list[tuple[int, list[str]]] = field(default_factory=list)
    held: set[str] = field(default_factory=set)


def pair(
    dividends: Iterable[Dividend],
    entries: Iterable[tuple[int, str]],
    spans: dict[str, tuple[str, str]],
    apart: Iterable[tuple[int, str]] = (),
) -> Pairing:
    """Pair the reader's entries, (id, day) of dividend rows that keep no
    ex-date, with the dividends they could be, by `spans` (`windows`). A pair
    in `apart` is one the reader said is not one dividend, and is never made
    again.

    An entry two dividends could be is asked about by entry; a dividend two
    entries could be, by dividend, unless one of its entries is already asked
    about, whose answer settles it first."""
    listed = [d for d in dividends if d.ex_date in spans]
    entries = list(entries)
    refused = set(apart)
    claims: dict[int, list[str]] = {
        tx_id: [
            d.ex_date
            for d in listed
            if inside(day, spans[d.ex_date]) and (tx_id, d.ex_date) not in refused
        ]
        for tx_id, day in entries
    }
    out = Pairing()
    asked = {tx_id for tx_id, xs in claims.items() if len(xs) >= 2}
    out.by_entry = [(tx_id, claims[tx_id]) for tx_id, _ in entries if tx_id in asked]
    for d in listed:
        could = [tx_id for tx_id, _ in entries if d.ex_date in claims[tx_id]]
        if not could:
            continue
        out.held.add(d.ex_date)
        if len(could) == 1 and len(claims[could[0]]) == 1:
            (out.doubles if d.estimate_id is not None else out.recognised).append((could[0], d.ex_date))
        elif len(could) >= 2 and not asked.intersection(could):
            out.by_dividend.append((d.ex_date, could))
    return out
