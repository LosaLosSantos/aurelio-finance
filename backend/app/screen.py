"""Where the reader is, in words: the page on screen when a question was asked.

The reader moves around the app, and the chat has to move with them. The
panel's state already lived above the tabs, so a conversation survived
navigation; what it did not know was what was in front of the reader. Its
context is the whole picture, and "why is this number so low?" asked on one
account's page reached the model with two cash registers in it and nothing to
say which one "this" was. Not a missing figure: a missing REFERENT.

THE LEVEL is the object a page is titled after — the last crumb of its
breadcrumb. A tab (the Dashboard, the Portfolio) is a page about everything, an
account's page is about one account, a situation's about one dated photograph,
a real asset's or a debt's about that one thing, an analysis's about one run. Below that there is nothing to point at: the app
selects no row, and a hover is not an intent. So "should I sell?" on Portfolio
arrives saying that nothing on it is selected, rather than with a first row the
model would be tempted to read as the subject.

WHAT IT CARRIES depends on whether the model can already read the thing.

- Already in the picture: a pointer, by NAME — "its cash is the 'Broker B' line
  of the cash register" — never by id (`tools._institution` says why a model
  must never be handed a foreign key to guess with).
- Not in the picture, but bounded and local: the data itself, for the message
  being answered and no other. A situation that is not the latest is on screen
  and nowhere in the picture, and a pointer to something the model cannot read
  is worse than no pointer. This is `chat.py`'s own rule for what earns context
  rather than a tool — bounded, always relevant, no network — and a thing on
  the reader's screen is relevant by construction.
- A document: the tool that already reads it. An analysis run is `read_analysis`.
- Not bounded: said out loud. The Dashboard's history is a point per event
  date; the note says those points are not in front of the model, so rule 2
  applies instead of a guess.

A page that does not resolve — its account deleted from another window — falls
back ONE level, to the page it was opened from. A question is never refused
because of the screen.

WHAT IT MUST NEVER REACH. Only `chat.py` imports this module, and a test keeps
it that way. The analyzer's sub-agents read `advisor.build_portfolio_context`
and `advisor.build_person_context`, which take a session and nothing else; the
MCP server reads `advisor.build_context`, which does the same; and the write
tools answer `(db, call)`. None of them has a parameter a page could travel
through, and none of them imports this. The screen is the reader's, and the
chain's asymmetry and an outside assistant's screenless view are code, not
intentions.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import crud, dated, models, schemas


@dataclass(frozen=True)
class Screen:
    """A page, resolved against the database.

    `label` is what is stored with the question and shown under it: the path
    through the app, in the app's own words. `note` is what the model reads for
    the message being answered — the label, then what that screen shows and
    whether the picture already holds it."""

    label: str
    note: str


RECORDS = {
    "wealth": "Records → Wealth",
    "real": "Records → Real assets",
    "debts": "Records → Debts",
    "cash": "Records → Cash flow",
}


def resolve(db: Session, page: schemas.ChatPage) -> Screen:
    """The page as a label and a note. Never raises for a page that is gone:
    it answers for the level above instead."""
    if isinstance(page, schemas.ChatPageSituation):
        return _situation(db, page)
    if isinstance(page, schemas.ChatPageAccount):
        return _account(db, page.institution_id)
    if isinstance(page, schemas.ChatPageRealAsset):
        return _real_asset(db, page.real_asset_id)
    if isinstance(page, schemas.ChatPageDebt):
        return _debt(db, page.liability_id)
    if isinstance(page, schemas.ChatPageRecords):
        return _records(db, page.section)
    if isinstance(page, schemas.ChatPageAnalysis):
        return _analysis(db, page.run_id)
    if isinstance(page, schemas.ChatPageAnalyses):
        return _analyses(db)
    if isinstance(page, schemas.ChatPagePortfolio):
        return _screen(
            "Portfolio",
            "The Portfolio page: every investment position, the tax estimate "
            "and the transaction ledger, all of it in the picture — the ledger "
            "on screen lists every entry, where the picture carries the most "
            "recent and says how many older ones it left out. The page is about "
            "ALL the positions and nothing on it is selected: 'this' is not the "
            "first row. Its look-through section is what `get_look_through` "
            "reads.",
        )
    if isinstance(page, schemas.ChatPageProfile):
        return _screen(
            "Profile",
            "The Profile page: the questionnaire and the goals, both in the "
            "picture, and the settings for the base currency and the tax "
            "estimate, which the picture's figures already use.",
        )
    return _screen(
        "Dashboard",
        "The Dashboard: net worth, the allocation and the monthly cash flow — "
        "the same figures as in the picture — and a chart of net worth OVER "
        "TIME. The chart's points are NOT in the picture: no past value of net "
        "worth is in front of you, so a question about how it moved has no "
        "figures to be answered from.",
    )


def _screen(label: str, says: str) -> Screen:
    return Screen(label=label, note=f"{label}\n{says}")


def _records(db: Session, section: str) -> Screen:
    label = RECORDS[section]
    if section == "wealth":
        names = [i.name for i in crud.get_institutions(db)]
        if not names:
            return _screen(label, "The list of institutions, which is empty.")
        return _screen(
            label,
            f"The list of institutions: {', '.join(names)}. Each one's cash is "
            "its line in the picture's cash register, and its positions are "
            "the ones marked '@ <its name>'.",
        )
    if section == "real":
        return _screen(
            label,
            "The list of real assets, each with its latest valuation — which "
            "is what the picture carries.",
        )
    if section == "debts":
        return _screen(
            label,
            "The list of debts, each with its latest outstanding balance — "
            "which is what the picture carries.",
        )
    transfers = len(crud.get_transfers(db))
    return _screen(
        label,
        "Income sources, expenses, transfers between accounts and PACs. "
        "Income, expenses and PACs are in the picture. The individual "
        f"transfers are NOT — {transfers} on screen — only what they add to and "
        "take from each account in the picture's cash register.",
    )


def _account(db: Session, institution_id: int) -> Screen:
    inst = crud.get_institution(db, institution_id)
    if inst is None:
        return _records(db, "wealth")
    label = f"{RECORDS['wealth']} → {inst.name}"
    situations = crud.get_snapshots_for_institution(db, inst.id)
    if situations:
        listed = ", ".join(
            f"{s.date} ({_positions(len(s.holdings))})" for s in situations
        )
        photos = (
            "Its dated investment situations are NOT in the picture; on "
            f"screen, by date: {listed}."
        )
    else:
        photos = "It has no dated investment situations."
    return _screen(
        label,
        f"The account page of {inst.name}: its cash register and the list of "
        f"its situations. Its cash is the '{inst.name}' line of the picture's "
        f"cash register, and its positions are the ones marked '@ {inst.name}'. "
        + photos,
    )


def _situation(db: Session, page: schemas.ChatPageSituation) -> Screen:
    snap = crud.get_snapshot(db, page.snapshot_id)
    if snap is None or snap.institution_id != page.institution_id:
        return _account(db, page.institution_id)
    inst = snap.institution
    # "Latest" means the one IN FORCE today, the one the picture reads, and
    # not the newest row: a photograph dated ahead waits for its day.
    today = dated.today()
    in_force = dated.latest_on_or_before(
        crud.get_snapshots_for_institution(db, inst.id), today
    )
    if snap.date > today:
        which = "it is dated after today, so nothing in the picture counts it yet"
    elif in_force is not None and in_force.id == snap.id:
        which = f"it is the situation {inst.name} is read from today"
    else:
        which = (
            f"it is NOT the one {inst.name} is read from today, which is the "
            f"situation of {in_force.date}"
        )
    rows = [_holding(h) for h in snap.holdings]
    held = "\n".join(rows) if rows else "It records no positions at all."
    return _screen(
        f"{RECORDS['wealth']} → {inst.name} → situation of {snap.date}",
        f"The situation of {snap.date} at {inst.name}: a photograph of what was "
        f"held there that day, as the reader recorded it; {which}. It is not in "
        "the picture, whose positions are projected from the situation each "
        "account is read from today and the ledger — so here it is, each "
        "figure in its own currency:\n" + held,
    )


def _positions(n: int) -> str:
    return "1 position" if n == 1 else f"{n} positions"


def _holding(h: models.Holding) -> str:
    """One row of a situation as it was typed: the arithmetic when there is
    one, the cost only when it is known, and nothing converted — the currency
    goes with every figure, like every typed figure in the picture."""
    head = f"- {h.asset_name} [{h.asset_class or 'n/a'}]" + (f" {h.symbol}" if h.symbol else "")
    parts = []
    if h.quantity is not None and h.unit_price is not None and h.value is not None:
        parts.append(f"qty {h.quantity:g} x {h.unit_price:.2f} = {h.value:.2f} {h.currency}")
    elif h.value is not None:
        parts.append(f"{h.value:.2f} {h.currency}")
    else:
        parts.append("no value recorded")
    if h.cost_basis is None:
        parts.append("cost unknown")
    else:
        parts.append(
            f"cost {h.cost_basis:.2f} {h.currency}" + (" (estimated)" if h.cost_estimated else "")
        )
    if h.distribution_policy:
        parts.append(schemas.POLICY_WORDS.get(h.distribution_policy, h.distribution_policy))
    return f"{head}: " + "; ".join(parts)


def _real_asset(db: Session, real_asset_id: int) -> Screen:
    """A real asset's page: every valuation on record, and the equity line the
    page draws from the debts that finance it. The picture carries only the
    newest valuation, so a question about how its value moved needs the rest —
    one asset's history, bounded by how often its owner values it."""
    asset = crud.get_real_asset(db, real_asset_id)
    if asset is None:
        return _records(db, "real")
    label = f"{RECORDS['real']} → {asset.name}"
    valuations = crud.get_valuations_for_real_asset(db, asset.id)
    listed = (
        "\n".join(f"- {v.date}: {v.value:.2f} {asset.currency}" for v in valuations)
        if valuations
        else "It has no valuations yet."
    )
    financed_by = [li.name for li in crud.get_liabilities(db) if li.real_asset_id == asset.id]
    debts = (
        f" The debts that finance it, each a line of the picture's Debts: "
        f"{', '.join(financed_by)}; the page works out the equity against them."
        if financed_by
        else " No debt on record finances it."
    )
    return _screen(
        label,
        f"The page of the real asset '{asset.name}' [{asset.category or 'n/a'}]: its "
        "valuations over time. The picture carries only its newest valuation, "
        f"under Real assets.{debts} Every valuation on record, oldest first, in "
        "the asset's own currency:\n" + listed,
    )


def _debt(db: Session, liability_id: int) -> Screen:
    """A debt's page: its outstanding balance over time. The picture carries
    the newest balance, the rate and the asset it finances; the history is what
    "how fast is this going down?" needs."""
    debt = crud.get_liability(db, liability_id)
    if debt is None:
        return _records(db, "debts")
    label = f"{RECORDS['debts']} → {debt.name}"
    balances = crud.get_balances_for_liability(db, debt.id)
    listed = (
        "\n".join(f"- {b.date}: {b.balance:.2f} {debt.currency}" for b in balances)
        if balances
        else "It has no balances yet."
    )
    return _screen(
        label,
        f"The page of the debt '{debt.name}' [{debt.kind or 'n/a'}]: its "
        "outstanding balance over time. The picture carries only its newest "
        "balance, with its rate and the asset it finances, under Debts. Every "
        "balance on record, oldest first, in the debt's own currency:\n" + listed,
    )


def _analyses(db: Session) -> Screen:
    latest = crud.get_latest_chain_run(db)
    if latest is None:
        return _screen("Past analyses", "The list of analysis runs, which is empty.")
    return _screen(
        "Past analyses",
        f"The list of past analysis runs. The latest is run {latest.id}, "
        f"finished {dated.local_day(latest.created_at)}, and only its opening lines are in "
        "the picture; `read_analysis` reads any run by its id.",
    )


def _analysis(db: Session, run_id: int) -> Screen:
    run = db.get(models.ChainRun, run_id)
    if run is None:
        return _analyses(db)
    latest = crud.get_latest_chain_run(db)
    where = (
        "It is the latest, so its opening lines are in the picture."
        if latest is not None and latest.id == run.id
        else "It is not the latest, and nothing of it is in the picture."
    )
    return _screen(
        f"Analysis run {run.id}",
        f"Analysis run {run.id}, finished {dated.local_day(run.created_at)}, open in the "
        f"main column. {where} Call `read_analysis` with run_id={run.id} for "
        "what it says.",
    )
