"""No amount is stored without saying what currency it is in.

An empty currency used to mean EUR. That was true only while EUR was the only
base the app could have, and the day the base can be something else it becomes
a lie about every row written afterwards: a balance typed as 1000 dollars,
stored with no currency, would be read back as 1000 euro. Migration
a7d2e94c10b8 wrote the old meaning into the existing rows once; these tests
hold the other half — nothing new can arrive empty, through any door.

The fix that was NOT chosen is the reason for the second test. Filling in the
current base on a write that omits the currency sounds equivalent, but every
update here replaces all settable columns (`crud._update`), so a form that does
not send the field would rewrite a row's stated currency with the base on each
save. A refusal writes nothing.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app import models, tools
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()


def _rows(client) -> dict[str, int]:
    """One row of every kind that carries a currency, each stated in USD."""
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    other = client.post("/api/institutions", json={"name": "Bank"}).json()["id"]

    def made(r):
        assert r.status_code == 201, r.text
        return r.json()["id"]

    sid = made(client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}))
    return {
        "institution": iid,
        "other": other,
        "snapshot": sid,
        "holding": made(client.post(
            f"/api/snapshots/{sid}/holdings",
            json={"asset_name": "Apple", "value": 100, "currency": "USD"},
        )),
        "real_asset": made(client.post("/api/real-assets", json={"name": "Flat", "currency": "USD"})),
        "liability": made(client.post("/api/liabilities", json={"name": "Loan", "currency": "USD"})),
        "income": made(client.post("/api/income-sources", json={"name": "Salary", "amount": 1, "currency": "USD"})),
        "expense": made(client.post("/api/expenses", json={"name": "Rent", "amount": 1, "currency": "USD"})),
        "anchor": made(client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": TODAY, "amount": 1, "currency": "USD"},
        )),
        "transfer": made(client.post(
            "/api/transfers",
            json={"date": TODAY, "from_institution_id": iid, "to_institution_id": other,
                  "amount": 1, "currency": "USD", "to_currency": "USD"},
        )),
        "goal": made(client.post("/api/goals", json={"name": "House", "currency": "USD"})),
    }


# Every door that writes a currency: (method, path, a payload complete but for
# the currency, the path that reads the row back). Paths are templates over the
# ids `_rows` made.
DOORS = [
    ("post", "/api/snapshots/{snapshot}/holdings", {"asset_name": "Coca-Cola", "value": 5}, None),
    ("put", "/api/holdings/{holding}", {"asset_name": "Apple", "value": 100}, "/api/holdings/{holding}"),
    ("post", "/api/real-assets", {"name": "Car"}, None),
    ("put", "/api/real-assets/{real_asset}", {"name": "Flat"}, "/api/real-assets/{real_asset}"),
    ("post", "/api/liabilities", {"name": "Card"}, None),
    ("put", "/api/liabilities/{liability}", {"name": "Loan"}, "/api/liabilities/{liability}"),
    ("post", "/api/income-sources", {"name": "Bonus", "amount": 1}, None),
    ("put", "/api/income-sources/{income}", {"name": "Salary", "amount": 1}, "/api/income-sources/{income}"),
    ("post", "/api/expenses", {"name": "Gym", "amount": 1}, None),
    ("put", "/api/expenses/{expense}", {"name": "Rent", "amount": 1}, "/api/expenses/{expense}"),
    ("post", "/api/institutions/{other}/cash-anchors", {"date": TODAY, "amount": 1}, None),
    ("put", "/api/cash-anchors/{anchor}", {"date": TODAY, "amount": 1}, "/api/institutions/{institution}/cash-anchors"),
    ("post", "/api/transfers", {"date": TODAY, "from_institution_id": None, "to_institution_id": None, "amount": 1, "to_currency": "USD"}, None),
    ("put", "/api/transfers/{transfer}", {"date": TODAY, "amount": 1, "to_currency": "USD"}, "/api/transfers/{transfer}"),
    ("post", "/api/goals", {"name": "Car"}, None),
    ("put", "/api/goals/{goal}", {"name": "House"}, "/api/goals/{goal}"),
]


@pytest.mark.parametrize("method,path,payload,read", DOORS, ids=[f"{d[0]} {d[1]}" for d in DOORS])
def test_a_write_that_does_not_say_its_currency_is_refused(client, method, path, payload, read):
    ids = _rows(client)
    url = path.format(**ids)

    missing = getattr(client, method)(url, json=payload)
    assert missing.status_code == 422, missing.text
    assert any(e["loc"][-1] == "currency" for e in missing.json()["detail"]), missing.text

    blank = getattr(client, method)(url, json={**payload, "currency": "   "})
    assert blank.status_code == 422, blank.text
    assert "say which currency" in blank.text


@pytest.mark.parametrize(
    "method,path,payload,read",
    [d for d in DOORS if d[0] == "put"],
    ids=[d[1] for d in DOORS if d[0] == "put"],
)
def test_an_update_that_leaves_the_currency_out_does_not_touch_the_one_stated(
    client, method, path, payload, read
):
    """The case the refusal was chosen for. A PUT replaces every settable
    column, so the alternative — filling in the base when the field is absent —
    would have turned this row's USD into EUR on a save that never mentioned
    the currency at all."""
    ids = _rows(client)

    assert client.put(path.format(**ids), json=payload).status_code == 422

    body = client.get(read.format(**ids)).json()
    rows = body if isinstance(body, list) else [body]
    assert [r["currency"] for r in rows] == ["USD"]


def test_a_stated_currency_is_kept_without_its_padding(client):
    iid = client.post("/api/institutions", json={"name": "Bank"}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": TODAY, "amount": 10, "currency": " USD "},
    )
    assert r.status_code == 201, r.text
    assert r.json()["currency"] == "USD"


@pytest.mark.parametrize(
    "model,fields",
    [
        (models.Holding, {"asset_name": "Apple", "value": 1.0}),
        (models.RealAsset, {"name": "Flat"}),
        (models.Liability, {"name": "Loan"}),
        (models.IncomeSource, {"name": "Salary", "amount": 1.0}),
        (models.Expense, {"name": "Rent", "amount": 1.0}),
        (models.CashAnchor, {"date": TODAY, "amount": 1.0}),
        (models.Transfer, {"date": TODAY, "amount": 1.0}),
        (models.Goal, {"name": "House"}),
    ],
    ids=lambda v: v.__name__ if isinstance(v, type) else "",
)
def test_the_table_itself_refuses_an_amount_with_no_currency(client, model, fields):
    """The API is one door; the column is the wall behind all of them. A write
    that reaches the table some other way — a script, a future tool that builds
    a model directly — is refused by SQLite rather than stored as a row whose
    currency every reader would have to guess."""
    iid = client.post("/api/institutions", json={"name": "Bank"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    parent = {
        models.Holding: {"snapshot_id": sid},
        models.CashAnchor: {"institution_id": iid},
    }.get(model, {})

    with SessionLocal() as db:
        db.add(model(**fields, **parent))
        with pytest.raises(IntegrityError, match="NOT NULL constraint failed"):
            db.commit()


def test_the_chat_cannot_draw_a_card_for_an_asset_with_no_currency(client):
    """The card shows the currency and the reader confirms it, so the model has
    to state one — the tool does not fill in "the app's own" behind the card."""
    with pytest.raises(ValidationError) as missing:
        tools.AddRealAssetArgs(name="gold necklace", value=500)
    assert "currency" in str(missing.value)

    with pytest.raises(ValidationError) as blank:
        tools.AddRealAssetArgs(name="gold necklace", value=500, currency=" ")
    assert "say which currency" in str(blank.value)
