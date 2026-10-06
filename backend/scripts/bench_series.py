"""Time the net worth series on a synthetic database: python -m scripts.bench_series [YEARS...]

The claim this script exists to keep honest is a performance one, and a
performance claim nobody can re-run is a story. The numbers in the commit that
made the series linear (`366 ms and 97 queries at ten years, from 1,407 ms and
3,221`) came from here, so the next person to touch `compute_net_worth_series`
or `_cash_totals_by_date` can check whether they still hold instead of
believing them.

It builds the shape this app actually has — a handful of institutions, a
photograph every six months, a purchase every month, one cash anchor each —
and grows it by years. What matters is not the absolute milliseconds (they are
this laptop's) but the two columns that say WHY they moved:

* `SQL` must stay flat in the number of points. It is what went from 3,221 to
  97: the tables are read once for the whole series instead of once per
  institution per sample date. A count that climbs with the points means
  something started querying inside the loop again.
* `per point` still grows with the LEDGER, because every sample date replays
  the entries after its own anchor. That is linear work per point and it is
  the honest cost of one mechanism for every point; it is not the defect that
  was removed.

DATABASE_URL is pinned to a scratch file and the file is deleted first, so this
can never measure — or touch — backend/data.db.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import sys
import tempfile
import time

# backend/ — this file is backend/scripts/bench_series.py — so `app` imports
# whether the caller ran us from backend/ or from anywhere else.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

_SCRATCH = pathlib.Path(tempfile.gettempdir()) / "aurelio_bench.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_SCRATCH}"
os.environ["AURELIO_SKIP_MIGRATIONS"] = "1"

from sqlalchemy import event  # noqa: E402

from app import analytics, models  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402

INSTITUTIONS = 4
SYMBOLS = ("VWCE.MI", "SWDA.MI", "AGGH.MI")
PHOTO_EVERY_DAYS = 182
BUY_EVERY_DAYS = 30


def _populate(db, years: int) -> int:
    """A history `years` long, and the number of ledger entries it took."""
    today = datetime.date.today()
    start = today - datetime.timedelta(days=365 * years)
    entries = 0
    for i in range(INSTITUTIONS):
        inst = models.Institution(name=f"Bank {i}")
        db.add(inst)
        db.flush()
        db.add(
            models.CashAnchor(
                institution_id=inst.id, date=start.isoformat(), amount=5_000, currency="EUR"
            )
        )
        day = start
        while day <= today:
            snap = models.Snapshot(institution_id=inst.id, date=day.isoformat())
            db.add(snap)
            db.flush()
            for symbol in SYMBOLS:
                db.add(
                    models.Holding(
                        snapshot_id=snap.id, asset_name=symbol, symbol=symbol,
                        asset_class="fund_etf", quantity=10, value=1_000,
                        currency="EUR",
                    )
                )
            day += datetime.timedelta(days=PHOTO_EVERY_DAYS)
        day = start
        while day <= today:
            db.add(
                models.Transaction(
                    kind="buy", date=day.isoformat(), institution_id=inst.id,
                    asset_name=SYMBOLS[0], symbol=SYMBOLS[0],
                    asset_class="fund_etf", quantity=1, unit_price=100, amount=100,
                    currency="EUR", price_currency="EUR",
                )
            )
            entries += 1
            day += datetime.timedelta(days=BUY_EVERY_DAYS)
    db.commit()
    return entries


def _measure(years: int) -> dict:
    _SCRATCH.unlink(missing_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        entries = _populate(db, years)
        statements = 0

        def _count(*_args, **_kwargs) -> None:
            nonlocal statements
            statements += 1

        event.listen(engine, "before_cursor_execute", _count)
        try:
            began = time.perf_counter()
            series = analytics.compute_net_worth_series(db)
            elapsed = (time.perf_counter() - began) * 1000
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        began = time.perf_counter()
        analytics.compute_summary(db)
        summary_ms = (time.perf_counter() - began) * 1000
    finally:
        db.close()
        engine.dispose()
        _SCRATCH.unlink(missing_ok=True)
    return {
        "years": years, "entries": entries, "points": len(series),
        "series_ms": elapsed, "summary_ms": summary_ms, "sql": statements,
    }


def main(argv: list[str]) -> int:
    horizons = [int(a) for a in argv[1:]] or [3, 5, 10]
    print(f"{'years':>5} {'ledger':>7} {'points':>7} {'series':>9} "
          f"{'per point':>10} {'SQL':>6} {'summary':>9}")
    for years in horizons:
        r = _measure(years)
        print(
            f"{r['years']:>5} {r['entries']:>7} {r['points']:>7} "
            f"{r['series_ms']:>8.0f}ms {r['series_ms'] / max(r['points'], 1):>9.1f}ms "
            f"{r['sql']:>6} {r['summary_ms']:>8.0f}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
