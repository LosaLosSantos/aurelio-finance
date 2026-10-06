"""REST endpoints for the "income_sources" resource.

Income sources belong directly to the user (a flat resource, like institutions).
`kind` (active/passive) feeds the financial-independence analysis later on.

The five endpoints themselves are the standard set, built by
`flat_resource.make_flat_router` — this file is what is TRUE OF INCOME
specifically, and nothing else.
"""

from __future__ import annotations

from app import crud, models, schemas
from app.routers.flat_resource import make_flat_router

router = make_flat_router(
    path="/income-sources",
    tag="income_sources",
    noun="income source",
    model=models.IncomeSource,
    read_schema=schemas.IncomeSourceRead,
    create_schema=schemas.IncomeSourceCreate,
    list_all=crud.get_income_sources,
    create=crud.create_income_source,
    update=crud.update_income_source,
    delete=crud.delete_income_source,
)
