"""What a page says about an amount no rate converts (brief BA, the reader's
decision D2 (c), 2026-10-16).

An amount in a code the app has no rate for is counted as written, as if it
were in the base: kept rather than dropped, since a total short by a whole
account is as wrong as one inflated (`fx.Converter.to_base_or_as_stored`).
What a page says about it, in the order the reader acts on it:

1. what kind of code it is: not a currency code (a typo, corrected on its
   row), or a currency no source quotes (nothing to correct: the figure is in
   two units);
2. where it is written: the rows, by kind and name, newest first;
3. how much of each figure on the page is that code as written, signed.

The third is measured, not tagged. Brief V's notice said a volume of rows,
every amount passed through added up, which matched no figure: measured at
279acf8, a household's notice said 4,000.00 over 5 while 2,300.00 of its net
worth and 900.00 of its book were the code, and a monthly income of 100
reported 100.00 while 1,200.00 had reached the cash. Here each figure is
computed again with that code's amounts at 0 (`fx.Converter(zero=...)`), and
the difference is what the code adds, in whatever role it reached the figure:
a value, a cost, a debt taken off, a flow times its occurrences, a dividend of
an earlier stretch. A conversion added later is covered without being told
its role.

What it costs: one more pass of the page's computation per code, and only
while a code is passed through. Measured on 2026-10-16, one pass of each page
takes 0.4 to 25 ms on the demo and on a copy of the test database. The history
is not computed again (a year of daily events takes 189 ms a pass): its points
carry the codes they hold, and its last point is the net worth, whose share
the summary measures. Never a sum over its points.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import fx, models, schemas

# The rows said by name; beyond them, how many more.
ROWS_SAID = 5


def codes(conv: fx.Converter) -> list[str]:
    """The codes `conv` passed through as written, in a stable order."""
    return sorted(conv.unconverted)


def shares(
    figures: dict[str, float | None],
    again: Callable[[str], dict[str, float | None]],
    found: Iterable[str],
) -> dict[str, dict[str, float]]:
    """{code: {figure: how much of it the code is, as written}} for each code
    that moves a figure by a cent or more: `again(code)` is the same figures
    computed with that code at 0. A code that moves none is left out, since
    there is nothing on the page for the reader to act on (a situation it was
    written on that no total reads any more)."""
    out: dict[str, dict[str, float]] = {}
    for code in found:
        without = again(code)
        moved: dict[str, float] = {}
        for name, value in figures.items():
            # A figure the second pass has no entry for is one the code alone
            # made (an allocation's slice of nothing else): its share is all
            # of it. One that came out as None was not computed either time.
            other = without.get(name, 0.0)
            if value is None or other is None:
                continue
            if abs(value - other) >= 0.005:
                moved[name] = round(value - other, 2)
        if moved:
            out[code] = moved
    return out


def _named(db: Session) -> dict[int, str]:
    return {i.id: i.name for i in db.scalars(select(models.Institution))}


def rows_written_in(db: Session, wanted: Iterable[str]) -> dict[str, list[dict]]:
    """{code: [{kind, name, where}]}: every row whose currency is written as
    `code`, newest first where a row has a day, from the same columns
    `crud.get_currencies_on_record` reads."""
    wanted = [c for c in wanted if c]
    found: dict[str, list[tuple[str, dict]]] = {c: [] for c in wanted}
    if not wanted:
        return {}
    names = _named(db)

    def add(code: str, day: str, kind: str, name: str, where: str | None) -> None:
        if code in found:
            found[code].append((day, {"kind": kind, "name": name, "where": where}))

    for h, s in db.execute(
        select(models.Holding, models.Snapshot)
        .join(models.Snapshot, models.Holding.snapshot_id == models.Snapshot.id)
        .where(models.Holding.currency.in_(wanted))
    ):
        add(h.currency, s.date, "position", h.asset_name,
            f"{names.get(s.institution_id, 'an account')}, situation of {s.date}")
    for a in db.scalars(select(models.RealAsset).where(models.RealAsset.currency.in_(wanted))):
        add(a.currency, "", "real asset", a.name, None)
    for d in db.scalars(select(models.Liability).where(models.Liability.currency.in_(wanted))):
        add(d.currency, "", "debt", d.name, None)
    for i in db.scalars(select(models.IncomeSource).where(models.IncomeSource.currency.in_(wanted))):
        add(i.currency, "", "income", i.name, None)
    for e in db.scalars(select(models.Expense).where(models.Expense.currency.in_(wanted))):
        add(e.currency, "", "expense", e.name, None)
    for c in db.scalars(select(models.CashAnchor).where(models.CashAnchor.currency.in_(wanted))):
        add(c.currency, c.date, "cash balance", names.get(c.institution_id, "an account"), c.date)
    for t in db.scalars(
        select(models.Transfer).where(
            or_(models.Transfer.currency.in_(wanted), models.Transfer.to_currency.in_(wanted))
        )
    ):
        sides = (
            f"{names.get(t.from_institution_id, 'outside')} to "
            f"{names.get(t.to_institution_id, 'outside')}"
        )
        for code in {t.currency, t.to_currency}:
            add(code, t.date, "transfer", sides, t.date)
    for g in db.scalars(select(models.Goal).where(models.Goal.currency.in_(wanted))):
        add(g.currency, "", "goal", g.name, None)
    for t in db.scalars(
        select(models.Transaction).where(
            or_(
                models.Transaction.currency.in_(wanted),
                models.Transaction.price_currency.in_(wanted),
            )
        )
    ):
        for code in {t.currency, t.price_currency}:
            if code:
                add(code, t.date, f"{t.kind} in the ledger", t.asset_name, t.date)
    for p in db.scalars(
        select(models.AccumulationPlan).where(models.AccumulationPlan.currency.in_(wanted))
    ):
        add(p.currency, "", "plan", p.name, None)
    return {
        code: [row for _, row in sorted(rows, key=lambda r: r[0], reverse=True)]
        for code, rows in found.items()
    }


def items(db: Session, moved: dict[str, dict[str, float]]) -> list[dict]:
    """The payload's `unconverted`, one entry a code: what kind of code, the
    rows it is written on (the first `ROWS_SAID`, and how many more), and how
    much of each figure it is."""
    return entries(rows_written_in(db, moved), moved)


def entries(census: dict[str, list[dict]], moved: dict[str, dict[str, float]]) -> list[dict]:
    """`items` on a census already read, for a list of payloads that share it
    (a situation's list)."""
    out = []
    for code, share in moved.items():
        rows = census.get(code, [])
        out.append({
            "currency": code,
            "not_a_code": not schemas.is_currency_code(code),
            "rows": rows[:ROWS_SAID],
            "more_rows": max(len(rows) - ROWS_SAID, 0),
            "shares": share,
        })
    return out


def notice(
    db: Session,
    conv: fx.Converter,
    figures: dict[str, float | None],
    again: Callable[[str], dict[str, float | None]],
) -> list[dict]:
    """Everything a payload says about what `conv` passed through: [] when
    nothing was, and no second pass is made then."""
    found = codes(conv)
    if not found:
        return []
    return items(db, shares(figures, again, found))


def said(
    db: Session,
    conv: fx.Converter,
    result: dict,
    names: Iterable[str],
    again: Callable[[str], dict],
) -> list[dict]:
    """`notice` for a payload whose figures are some of its own fields, by
    name: `again(code)` is the payload computed with that code at 0."""
    names = tuple(names)

    def pick(payload: dict) -> dict[str, float | None]:
        return {name: payload[name] for name in names}

    return notice(db, conv, pick(result), lambda code: pick(again(code)))
