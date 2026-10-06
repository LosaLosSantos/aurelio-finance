"""The five endpoints every flat resource has, checked on both resources built
by `flat_resource.make_flat_router`.

Income sources and expenses used to be two hand-written routers, sixty lines
each and identical except for the noun. They are now one factory called twice,
which is only an improvement if the endpoints still answer the way they did —
including the parts nothing was asserting: that a PUT writes what it was sent,
that a missing id is a 404 naming what was looked for, and that a delete of
something already gone is a 404 rather than a silent 204.

Parameterised over both resources on purpose. The bug this guards against is
the two drifting apart, so a test that only ever looked at income would not see
it.
"""

from __future__ import annotations

import pytest

# (collection path, the field that classifies this resource, a value for it)
RESOURCES = [
    ("/api/income-sources", "kind", "active"),
    ("/api/expenses", "nature", "essential"),
]


def _payload(tag_field: str, tag_value: str, **over) -> dict:
    body = {
        "name": "Rent",
        tag_field: tag_value,
        "category": "housing" if tag_field == "nature" else "salary",
        "amount": 1200.0,
        "currency": "EUR",
        "frequency": "monthly",
        "start_date": "2026-01-01",
        "notes": "first",
    }
    body.update(over)
    return body


@pytest.mark.parametrize("path,tag_field,tag_value", RESOURCES)
def test_create_list_and_read_one(client, path, tag_field, tag_value):
    created = client.post(path, json=_payload(tag_field, tag_value))
    assert created.status_code == 201, created.text
    item = created.json()
    assert item[tag_field] == tag_value
    assert item["amount"] == 1200.0
    # The response carries what only the server can know.
    assert item["id"] > 0 and item["created_at"]

    listed = client.get(path)
    assert listed.status_code == 200
    assert [x["id"] for x in listed.json()] == [item["id"]]

    one = client.get(f"{path}/{item['id']}")
    assert one.status_code == 200 and one.json() == item


@pytest.mark.parametrize("path,tag_field,tag_value", RESOURCES)
def test_a_put_empties_the_boxes_it_sends_empty(client, path, tag_field, tag_value):
    """The half of the rule that used to be the whole of it.

    This test read `replaces every settable field`, and what it asserted was
    that a PUT leaving `notes` OUT clears them — "a payload that silently
    merges is how a field the user deleted comes back". The danger it names is
    real and the fix does not reopen it: a box the reader empties still clears,
    because emptying a box sends `null`, which is a statement. What changed is
    the other half — a field the form has no box for at all is now left alone
    instead of destroyed. See `crud._update`.
    """
    item = client.post(path, json=_payload(tag_field, tag_value)).json()

    replaced = client.put(
        f"{path}/{item['id']}",
        json={
            "name": "Rent (new flat)",
            "amount": 1350.0,
            "currency": "EUR",
            "notes": None,
            tag_field: None,
            "start_date": None,
        },
    )
    assert replaced.status_code == 200, replaced.text
    after = replaced.json()
    assert after["id"] == item["id"]
    assert after["name"] == "Rent (new flat)" and after["amount"] == 1350.0
    assert after["notes"] is None
    assert after[tag_field] is None
    assert after["start_date"] is None


@pytest.mark.parametrize("path,tag_field,tag_value", RESOURCES)
def test_delete_then_gone(client, path, tag_field, tag_value):
    item = client.post(path, json=_payload(tag_field, tag_value)).json()

    assert client.delete(f"{path}/{item['id']}").status_code == 204
    assert client.get(f"{path}/{item['id']}").status_code == 404
    assert client.get(path).json() == []
    # Deleting it a second time is a 404, not a second 204: "I removed it" and
    # "there was nothing there" are different answers.
    assert client.delete(f"{path}/{item['id']}").status_code == 404


@pytest.mark.parametrize("path,tag_field,tag_value", RESOURCES)
def test_missing_id_is_a_404_that_says_what_it_looked_for(
    client, path, tag_field, tag_value
):
    for call in (
        client.get(f"{path}/9999"),
        client.put(f"{path}/9999", json=_payload(tag_field, tag_value)),
        client.delete(f"{path}/9999"),
    ):
        assert call.status_code == 404, call.text
        assert "9999" in call.json()["detail"]


@pytest.mark.parametrize("path,tag_field,tag_value", RESOURCES)
def test_a_nameless_or_negative_entry_is_refused(client, path, tag_field, tag_value):
    blank = client.post(path, json=_payload(tag_field, tag_value, name=""))
    assert blank.status_code == 422

    negative = client.post(path, json=_payload(tag_field, tag_value, amount=-1))
    assert negative.status_code == 422


def test_the_two_resources_do_not_share_a_classifying_field(client):
    """`kind` and `nature` are not one column with four values.

    This is the reason the two tables were NOT merged, so it is worth one
    assertion: neither resource answers with the other's field, and neither
    accepts it as a way to set anything.
    """
    income = client.post(
        "/api/income-sources", json=_payload("kind", "active")
    ).json()
    expense = client.post("/api/expenses", json=_payload("nature", "essential")).json()

    assert "kind" in income and "nature" not in income
    assert "nature" in expense and "kind" not in expense
