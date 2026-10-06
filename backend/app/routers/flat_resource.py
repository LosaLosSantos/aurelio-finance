"""One router for a flat resource: create, list, read one, update, delete.

`income_sources.py` and `expenses.py` were sixty lines each and identical
character for character except for the noun — the same five endpoints, the same
`get_or_404` before the update and the delete, the same 201 and 204. Two copies
of a correct thing is two chances for the second one to answer differently, and
the routers are exactly where that shows up as a different status code for the
same mistake.

The resource's own crud functions are passed in rather than looked up: they stay
named (`crud.get_income_sources` is called from analytics and the advisor too),
and this file stays free of any knowledge of which tables exist.

NOTE: no `from __future__ import annotations` here, unlike every other module in
this package, and it is not an oversight. That import turns every annotation
into a string, and FastAPI would then have to resolve `payload: create_schema`
by name in this module's globals — where it does not exist, because it is an
argument. Evaluated eagerly, the annotation IS the schema object, which is what
FastAPI needs to know what the request body looks like.
"""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.deps import get_or_404


def make_flat_router(
    *,
    path: str,
    tag: str,
    noun: str,
    model: type,
    read_schema: type[BaseModel],
    create_schema: type[BaseModel],
    list_all: Callable[[Session], list[Any]],
    create: Callable[[Session, Any], Any],
    update: Callable[[Session, int, Any], Any],
    delete: Callable[[Session, int], Any],
) -> APIRouter:
    """Build the five standard endpoints for one flat resource.

    `path` is the collection path under /api ("/income-sources"); `noun` is how
    the docs name one of them ("income source").
    """
    router = APIRouter(prefix="/api", tags=[tag])
    one = path + "/{item_id}"
    a = "an" if noun[0] in "aeiou" else "a"

    @router.post(
        path,
        response_model=read_schema,
        status_code=status.HTTP_201_CREATED,
        summary=f"Create a new {noun}",
    )
    def create_item(payload: create_schema, db: Session = Depends(get_db)):
        return create(db, payload)

    @router.get(path, response_model=list[read_schema], summary=f"List all {noun}s")
    def list_items(db: Session = Depends(get_db)):
        return list_all(db)

    @router.get(
        one,
        response_model=read_schema,
        summary=f"Return a single {noun}, or 404 if it does not exist",
    )
    def get_item(item_id: int, db: Session = Depends(get_db)):
        return get_or_404(db, model, item_id)

    @router.put(one, response_model=read_schema, summary=f"Update {a} {noun}")
    def update_item(item_id: int, payload: create_schema, db: Session = Depends(get_db)):
        get_or_404(db, model, item_id)
        return update(db, item_id, payload)

    @router.delete(
        one,
        status_code=status.HTTP_204_NO_CONTENT,
        summary=f"Delete {a} {noun}",
    )
    def delete_item(item_id: int, db: Session = Depends(get_db)) -> None:
        get_or_404(db, model, item_id)
        delete(db, item_id)

    return router
