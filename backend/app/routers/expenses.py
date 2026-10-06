"""REST endpoints for the "expenses" resource.

Expenses belong directly to the user (a flat resource, like institutions).
`nature` (essential/discretionary) feeds the savings-rate analysis later on.

The five endpoints themselves are the standard set, built by
`flat_resource.make_flat_router` — this file is what is TRUE OF EXPENSES
specifically, and nothing else.
"""

from __future__ import annotations

from app import crud, models, schemas
from app.routers.flat_resource import make_flat_router

router = make_flat_router(
    path="/expenses",
    tag="expenses",
    noun="expense",
    model=models.Expense,
    read_schema=schemas.ExpenseRead,
    create_schema=schemas.ExpenseCreate,
    list_all=crud.get_expenses,
    create=crud.create_expense,
    update=crud.update_expense,
    delete=crud.delete_expense,
)
