"""What the ledger paid before an account's latest situation, proposed and
written on the reader's press (brief AW).

The walk is `positions.recover_paid`: every situation of an account, per row,
with the ledger between them, proposing for each row of a latest situation
what was paid that the row does not say. Measured at `8325ebd` on brief AV's
invented scenario: a row carried by the code before AV read 110.00 paid where
the ledger held 410.00. This module reads that walk with the reader's own
declines, turns it into what the Portfolio shows, writes a proposal the reader
accepts and remembers one they decline. Nothing here runs without a press: the
reader chose (2026-10-15) to see each figure before it is written.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app import crud, dated, fx, models, positions, schemas
from app.database import unit_of_work


class Refused(ValueError):
    """A press the app will not act on, in the reader's words (a 409)."""


def read(
    db: Session,
    conv: fx.Converter | None = None,
    inputs: positions.ProjectionInputs | None = None,
) -> positions.Recovery:
    """The walk, with the rows the reader declined as its barriers."""
    return positions.recover_paid(
        inputs if inputs is not None else positions.load_projection_inputs(db),
        conv if conv is not None else fx.Converter(db),
        day=dated.today(),
        declined=crud.declined_paid(db),
    )


def payload(recovery: positions.Recovery, names: dict[int, str]) -> dict[str, list[dict]]:
    """The Portfolio's two lists: the proposals, and the purchases left unread."""
    return {
        "paid_recovery": [
            {
                "holding_id": p.holding_id,
                "institution_id": p.institution_id,
                "institution": names.get(p.institution_id),
                "asset_name": p.asset_name,
                "symbol": p.symbol,
                "situation_date": p.situation_date,
                "quantity": p.quantity,
                "paid": p.paid,
                "units": p.units,
                "estimated": p.estimated,
                "since": p.since,
                "opening_paid": p.opening_paid,
                "opening_units": p.opening_units,
                "entries": [
                    {"date": e.date, "kind": e.kind, "quantity": e.quantity,
                     "amount": e.amount, "estimated": e.estimated}
                    for e in p.entries
                ],
                "row_paid": p.row_paid,
                "row_units": p.row_units,
                "row_estimated": p.row_estimated,
            }
            for p in recovery.proposals
        ],
        "paid_unread": [
            {
                "holding_id": u.holding_id,
                "institution_id": u.institution_id,
                "institution": names.get(u.institution_id),
                "asset_name": u.asset_name,
                "symbol": u.symbol,
                "situation_date": u.situation_date,
                "stated_units": u.stated_units,
                "walked_units": u.walked_units,
                "paid": u.paid,
                "units": u.units,
                "since": u.since,
                "purchases": u.purchases,
                "opening_paid": u.opening_paid,
            }
            for u in recovery.unread
        ],
    }


def _proposal_for(
    db: Session, found: dict[int, positions.PaidProposal], holding_id: int
) -> positions.PaidProposal:
    """The proposal the walk makes for a row now, or the refusal saying it
    makes none."""
    p = found.get(holding_id)
    if p is None:
        holding = db.get(models.Holding, holding_id)
        name = holding.asset_name if holding is not None else "this row"
        raise Refused(
            f"Nothing is proposed for {name} any more: its situations or the ledger "
            "changed since the page was loaded. Reload the Portfolio to see what is "
            "proposed now."
        )
    return p


def accept(db: Session, shown: list[schemas.PaidAcceptRow]) -> list[models.Holding]:
    """Write the proposals the reader accepted, each as its row's cost, all in
    one transaction or none.

    The figures written are the walk's own, worked out again now; the page's
    only say which proposal the reader saw, so one that changed since (an
    entry corrected in another tab, a situation added) is refused rather than
    written unseen. The cost is stored in the currency the row is read in, as
    "Start from the last one" stores it: a base figure under a dollar row would
    be converted a second time on the next reading."""
    conv = fx.Converter(db)
    inputs = positions.load_projection_inputs(db)
    found = {p.holding_id: p for p in read(db, conv, inputs).proposals}
    written: list[models.Holding] = []
    with unit_of_work(db):
        for row in shown:
            p = _proposal_for(db, found, row.holding_id)
            holding = db.get(models.Holding, row.holding_id)
            if abs(p.paid - row.paid) > 0.005 or not positions.units_agree(p.units, row.units):
                raise Refused(
                    f"What the ledger paid for {p.asset_name} changed since the page was "
                    "loaded. Reload the Portfolio to see the figures before you accept them."
                )
            listing = inputs.listing.get(holding.symbol) if holding.symbol else None
            currency = listing if listing else holding.currency
            cost = conv.from_base(p.paid, currency)
            if cost is None:
                raise Refused(
                    f"No exchange rate for {currency} is known today, so what was paid for "
                    f"{p.asset_name} cannot be written in that row's currency. Try again "
                    "when a rate is available."
                )
            every_unit = p.units >= holding.quantity or positions.units_agree(
                p.units, holding.quantity
            )
            crud.write_paid(db, holding, cost, None if every_unit else p.units, p.estimated)
            written.append(holding)
    for holding in written:
        db.refresh(holding)
    return written


def decline(db: Session, holding_id: int) -> None:
    """Remember that the reader declined a row's proposal: the walk starts again
    at that row, so it is never proposed again."""
    found = {p.holding_id: p for p in read(db).proposals}
    p = _proposal_for(db, found, holding_id)
    crud.decline_paid(
        db,
        holding_id,
        json.dumps(
            {"paid": round(p.paid, 2), "units": p.units, "since": p.since,
             "declined_on": dated.today()}
        ),
    )
