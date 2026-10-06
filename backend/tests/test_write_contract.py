"""The two contracts the schemas carry: what a caller may set on the way in,
and what a response always contains on the way out.

crud stopped copying payloads field by field: every create and update now goes
through `_columns(data)`, which turns a `*Create` into model kwargs wholesale.
That trade is a good one — thirteen hand-written copies were thirteen chances
to forget a line, and a forgotten line updates nothing and says nothing — but
it moves the risk. Before, a mistake cost one field on one model. Now the
`*Create` schema IS the allow-list, so a field that does not belong on one
would be written on every create and every update of that model.

The rule is therefore not a comment in crud.py. It is asserted here, once, for
every `*Create` in schemas.py: probability down, blast radius up, invariant
stated out loud.

The same shape then appeared on the way OUT. `schemas.API_OUT` tells the
OpenAPI document that a field with a default is always present in a response,
and the frontend's types are generated from that document — so the promise is
load-bearing at a distance. It is true for one reason: FastAPI serializes the
whole response model. Nothing asserts that reason, which makes it an invariant
holding by the SHAPE of the code, which is the same trade `_columns` made. So
it is asserted here too.
"""

from __future__ import annotations

import ast
import datetime
import pathlib
import typing

import pytest
from pydantic import BaseModel

from app import crud, schemas
from app.main import app

# Every `*Create` in schemas.py, including the child ones (PlanTargetCreate) —
# the rule is about the shape of the family, not about who happens to use it.
CREATE_SCHEMAS = sorted(
    (name, obj)
    for name, obj in vars(schemas).items()
    if isinstance(obj, type) and issubclass(obj, BaseModel) and name.endswith("Create")
)


def _annotated_types(annotation) -> set:
    """Every type mentioned in an annotation, `X | None` and `list[X]` included.

    A bare `is datetime.datetime` misses the form the field would actually be
    written in: `taken_at: datetime.datetime | None` is Optional[datetime], not
    datetime, and reads as clean while being the exact thing that breaks.
    """
    found = {annotation}
    for arg in typing.get_args(annotation):
        found |= _annotated_types(arg)
    return found


def _parent_kwargs() -> dict[str, set[str]]:
    """{'SnapshotCreate': {'institution_id'}, ...} — the names crud passes BY HAND
    beside a payload unpack.

    Read out of crud.py rather than listed here, because a list in a test is
    the same forgettable line the payload change removed from crud: a create
    added tomorrow is covered tomorrow, by nobody.
    """
    tree = ast.parse(pathlib.Path(crud.__file__).read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        schema = next(
            (
                a.annotation.attr
                for a in fn.args.args
                if isinstance(a.annotation, ast.Attribute)
                and a.annotation.attr.endswith("Create")
            ),
            None,
        )
        if schema is None:
            continue
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
            # models.X(parent_id=parent_id, **_some_payload(data))
            built_from_payload = any(
                k.arg is None and isinstance(k.value, ast.Call) for k in call.keywords
            )
            if built_from_payload:
                found.setdefault(schema, set()).update(
                    k.arg for k in call.keywords if k.arg is not None
                )
    return found


@pytest.mark.parametrize("name,schema", CREATE_SCHEMAS, ids=[n for n, _ in CREATE_SCHEMAS])
def test_a_create_schema_never_carries_what_the_caller_must_not_set(name, schema):
    fields = schema.model_fields

    # 1. The database's own columns. `id` is the database's to hand out and
    # `created_at` is its record of when it did; a payload that carried either
    # would let a request renumber a row or backdate its own arrival.
    #
    # `added_at` is the same column under the name a watchlist line reads
    # better as. It is listed rather than derived because the alternative — ask
    # each model which of its columns has a `default` — would also catch every
    # field the API is SUPPOSED to let a caller leave out, which is most of
    # them. Two names for one idea is the price; a third one should join them
    # here rather than be spelt differently in a schema and go unchecked.
    assert not {"id", "created_at", "added_at"} & set(fields), (
        f"{name} carries an identity column: _columns would write it on every save"
    )

    # 2. The parent. A snapshot belongs to the institution in its URL, not to
    # one in its body. crud passes that id by hand precisely so the payload
    # cannot, and the two failures are NOT symmetric: on the create a duplicate
    # kwarg is a loud TypeError, while the update takes the body's value
    # without a word and re-parents the row. It is the quiet half that does the
    # damage, so the check belongs on the schema, before either can happen.
    for parent in _parent_kwargs().get(name, set()):
        assert parent not in fields, (
            f"{name}.{parent} is the parent crud passes by hand: an update would "
            f"let the request move the row to another one"
        )

    # 3. Datetimes. `_columns` converts a date to its ISO string by asking
    # isinstance(value, datetime.date) — and datetime INHERITS from date, so a
    # datetime field would satisfy that test and write '2026-08-29T14:30:00'
    # into a column whose every other value is '2026-08-29'. Silently, on every
    # model with such a field, and only visible later as a date comparison that
    # stops matching. There are none today, which is exactly why the day one
    # arrives is the day this has to fail.
    for field, info in fields.items():
        assert datetime.datetime not in _annotated_types(info.annotation), (
            f"{name}.{field} is a datetime: _columns would store a timestamp in a "
            f"date column, because datetime is a subclass of date"
        )


def test_the_parent_ids_are_actually_found_in_crud():
    """The check above is only worth having if it found the parents at all: a
    walk that silently matched nothing would pass every schema forever."""
    parents = _parent_kwargs()
    assert parents["SnapshotCreate"] == {"institution_id"}
    assert parents["HoldingCreate"] == {"snapshot_id"}
    assert parents["CashAnchorCreate"] == {"institution_id"}
    assert parents["LiabilityBalanceCreate"] == {"liability_id"}
    assert parents["RealAssetValuationCreate"] == {"real_asset_id"}


# --- The other direction: what a response always contains -------------------


def _api_routes() -> list:
    """Every route FastAPI will actually serve, as it will serve it."""
    from fastapi.routing import APIRoute

    return [r for r in app.routes if isinstance(r, APIRoute)]


# The settings that would each stop a route sending the whole response model.
NARROWING = (
    "response_model_exclude_unset",
    "response_model_exclude_defaults",
    "response_model_exclude_none",
)


def test_no_route_narrows_its_response_body():
    """`API_OUT` promises a defaulted field is always PRESENT. Keep it true.

    It marks such fields required in the SERIALIZATION schema, which is what
    lets the frontend's generated types drop `| undefined` from every one of
    them. The promise rests entirely on FastAPI serializing the whole response
    model, and each of the settings below stops it doing that for one route.

    Set one, and the OpenAPI document goes on saying a field is guaranteed
    while the response omits it. Nothing fails on either side: the backend is
    doing what it was told, the frontend's types were generated from a document
    that was true when it was written, and the field simply is not there. That
    is the same silent shape the generated types were introduced to kill.

    Read off the live routes rather than grepped out of the source, so it also
    catches the setting arriving as a router default or through include_router.
    """
    for route in _api_routes():
        for setting in NARROWING:
            assert getattr(route, setting) is False, (
                f"{route.path} sets {setting}: API_OUT still tells the OpenAPI "
                f"document every defaulted field is present, and the frontend's "
                f"types are generated from it"
            )
        # The explicit forms of the same thing.
        for setting in ("response_model_exclude", "response_model_include"):
            assert getattr(route, setting) is None, (
                f"{route.path} sets {setting}: the response no longer matches "
                f"the schema the types were generated from"
            )


def test_the_route_scan_actually_sees_the_api():
    """The check above is only worth having if it looked at anything: a scan
    that matched no routes would pass every future mistake."""
    paths = {r.path for r in _api_routes()}
    assert "/api/dashboard/summary" in paths
    assert "/api/income-sources" in paths
    assert len(paths) > 40, f"only {len(paths)} routes found"
