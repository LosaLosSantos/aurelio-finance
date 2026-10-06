"""A stated figure is a question, and a fund's cost comes from the catalogue.

Run 2, on 2026-10-03, turned a questionnaire answer into a correction of the
records. The person had said a monthly spending was "not yet entered" in the
register; a line of the same amount had been entered since; the confidant,
which never sees the register, read the answer as current, the revision gave
way, and the synthesis told the person to enter the amount again. Nothing in
front of the roles said when the answer was given, and the day stored for it
was not that day anyway: a Save of the Profile form stamped every answer with
the day of the Save, and the chat's overwrite kept the first day.

The same run quoted the funds' costs from the model's memory while the fund
catalogue held them, keyed by the ISIN the holdings carry.

Every name, ISIN and amount here is invented.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest
from sqlalchemy import update

from app import advisor, catalogue, chain, crud, dated, models, tools
from app.database import SessionLocal

LONG_AGO = "2026-01-15T12:00:00+00:00"  # midday UTC: the same day in any zone within 11 hours
EARLIER = "2025-11-03T12:00:00+00:00"
DAYS = "The day in brackets is when each answer was recorded"


def _put(client, *answers: tuple[str, str, str, str]) -> None:
    r = client.put("/api/survey", json=[
        {"question_key": k, "topic": t, "question": q, "answer": a} for k, t, q, a in answers
    ])
    assert r.status_code == 200, r.text


def _backdate(key: str, stamp: str) -> None:
    with SessionLocal() as db:
        db.execute(
            update(models.SurveyResponse)
            .where(models.SurveyResponse.question_key == key)
            .values(created_at=stamp)
        )
        db.commit()


def _local_day(stamp: str) -> str:
    """The reader's day for a stored UTC stamp, worked out here rather than
    with the app's own rule, so the tests check that rule instead of reusing it."""
    return datetime.datetime.fromisoformat(stamp).astimezone().date().isoformat()


def _day_of(key: str) -> str:
    with SessionLocal() as db:
        row = next(r for r in crud.get_survey_responses(db) if r.question_key == key)
        return _local_day(row.created_at)


AGE = ("eta", "About you", "Your age?", "41")
RISK = ("rischio", "Risk & values", "How do you take a fall of the markets?", "I hold on")
BOAT = (
    "spesa_barca",
    "Spending",
    "Is there a regular cost you have not recorded yet?",
    "The mooring of the boat, about 95 EUR a month, not yet entered in the register.",
)


# --- The day of each answer -------------------------------------------------------


def test_each_answer_reaches_the_confidant_with_the_day_it_was_recorded(client):
    _put(client, AGE, BOAT)
    _backdate("spesa_barca", LONG_AGO)

    with SessionLocal() as db:
        person = advisor.build_person_context(db)
        analyst = advisor.build_portfolio_context(db)

    assert f"Today is {dated.today()}." in person
    assert DAYS in person
    assert (
        "- [2026-01-15] Is there a regular cost you have not recorded yet?: "
        "The mooring of the boat, about 95 EUR a month, not yet entered in the register."
    ) in person
    assert f"- [{dated.today()}] Your age?: 41" in person
    assert DAYS not in analyst and "mooring" not in analyst, "the analyst is blind to the person"


def test_the_chat_reads_the_same_dated_answers(client):
    """One renderer for the questionnaire: the chat, the MCP server and the
    confidant read the same lines, dates included."""
    _put(client, BOAT)
    _backdate("spesa_barca", LONG_AGO)

    with SessionLocal() as db:
        picture = advisor.build_context(db)

    assert DAYS in picture
    assert "- [2026-01-15] Is there a regular cost you have not recorded yet?: " in picture


def test_the_day_is_the_readers_own_not_the_stored_utc_one(client):
    """Stored in UTC, read as the local day: the rule the chat already applies
    to an analysis's date. Near midnight the two days differ."""
    _put(client, AGE)
    late = "2026-01-15T23:30:00+00:00"
    _backdate("eta", late)

    with SessionLocal() as db:
        assert f"- [{_local_day(late)}] Your age?: 41" in advisor.build_person_context(db)


def test_a_save_keeps_the_day_of_an_answer_it_sends_back_unchanged(client):
    """The Profile form posts every answer at each Save, and the same button
    saves the tax rates and the base currency. Every answer used to come back
    dated with the day of the Save."""
    _put(client, AGE, RISK)
    _backdate("eta", LONG_AGO)
    _backdate("rischio", LONG_AGO)

    _put(client, AGE, RISK[:3] + ("I sell, then regret it",))

    assert _day_of("eta") == "2026-01-15"
    assert _day_of("rischio") == dated.today(), "a changed answer is dated the day it changed"


def test_an_answer_the_chat_recorded_keeps_its_day_through_a_save_of_the_form(client):
    """The case of run 2: the chat records an answer under a key the form does
    not own, and the form carries it back, untouched, at every Save."""
    _put(client, AGE)
    with SessionLocal() as db:
        crud.upsert_survey_response(db, BOAT[0], BOAT[3], topic=BOAT[1], question=BOAT[2])
    _backdate("spesa_barca", LONG_AGO)

    _put(client, AGE, BOAT)

    assert _day_of("spesa_barca") == "2026-01-15"


def test_the_chat_changing_an_answer_dates_it_that_day_and_repeating_it_does_not(client):
    _put(client, AGE)
    _backdate("eta", EARLIER)

    with SessionLocal() as db:
        crud.upsert_survey_response(db, "eta", "41")
    assert _day_of("eta") == "2025-11-03"

    with SessionLocal() as db:
        crud.upsert_survey_response(db, "eta", "42")
    assert _day_of("eta") == dated.today()


def test_the_card_for_a_changed_answer_no_longer_says_answers_are_undated():
    said = tools._PROFILE_CONSEQUENCE
    assert "not dated" not in said
    assert "the day it was recorded" in said
    assert "not kept in history" in said


# --- A fund's facts, from the catalogue -----------------------------------------------

FUNDS = pd.DataFrame(
    [
        {
            "name": "Esempio World Equity UCITS ETF Acc", "ticker": "EWEA",
            "dividends": "Accumulating", "ter": 0.17, "size": 1234,
            "replication": "Full replication", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1500, "hedged": False,
        },
        {
            "name": "Esempio Euro Bond UCITS ETF EUR Hedged Dist", "ticker": "EEBD",
            "dividends": "Distributing", "ter": 0.09, "size": 87,
            "replication": "Swap based Unfunded", "domicile_country": "Luxembourg",
            "currency": "EUR", "number_of_holdings": 40, "hedged": True,
        },
    ],
    index=pd.Index(["IE000EXMPL01", "LU000EXMPL02"], name="isin"),
)


def _load_catalogue(client, monkeypatch) -> str:
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: FUNDS)
    r = client.post("/api/instruments/catalogue/refresh")
    assert r.status_code == 200, r.text
    return _local_day(r.json()["fetched_at"])


def _hold(client, *holdings: dict) -> None:
    iid = client.post("/api/institutions", json={"name": "Banca Esempio"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-02-01"}
    ).json()["id"]
    for h in holdings:
        r = client.post(
            f"/api/snapshots/{sid}/holdings",
            json={"quantity": 10, "unit_price": 50, "currency": "EUR", **h},
        )
        assert r.status_code in (200, 201), r.text


WORLD = {"asset_name": "Esempio World", "asset_class": "fund_etf", "symbol": "EWEA.MI",
         "isin": "IE000EXMPL01", "distribution_policy": "acc"}
BOND = {"asset_name": "Esempio Euro Bond", "asset_class": "bond", "isin": "lu000exmpl02"}
NO_ISIN = {"asset_name": "Fondo Senza Codice", "asset_class": "fund_etf", "symbol": "FSC.MI"}
OUTSIDE = {"asset_name": "Fondo Fuori Elenco", "asset_class": "fund_etf", "isin": "IE000NOTHER9"}
SHARE = {"asset_name": "Azione Esempio", "asset_class": "equity", "isin": "IT000EXMPL03"}


def _line(ctx: str, name: str) -> str:
    return next(ln for ln in ctx.splitlines() if ln.startswith(f"- {name} "))


def test_a_held_fund_reaches_the_analyst_with_its_cost_from_the_catalogue(client, monkeypatch):
    day = _load_catalogue(client, monkeypatch)
    _hold(client, WORLD)

    with SessionLocal() as db:
        analyst = advisor.build_portfolio_context(db)

    assert (
        "; accumulating; ISIN IE000EXMPL01, catalogue: TER 0.17% a year, domicile Ireland, "
        "replication Full replication, not currency-hedged, fund size 1234 M EUR"
    ) in _line(analyst, "Esempio World")
    assert (
        f'- The facts after "catalogue:" are from justETF\'s list of funds, as the app '
        f"downloaded it on {day}."
    ) in analyst


def test_a_fund_filed_under_another_class_is_described_and_its_policy_fills_a_gap(
    client, monkeypatch
):
    """Filed as a bond, typed in lower case, with no dividend policy on the
    holding: the catalogue knows the ISIN, so it describes the fund, and its
    policy is said because the holding says none."""
    _load_catalogue(client, monkeypatch)
    _hold(client, BOND)

    with SessionLocal() as db:
        line = _line(advisor.build_portfolio_context(db), "Esempio Euro Bond")

    assert (
        "ISIN LU000EXMPL02, catalogue: TER 0.09% a year, distributing, domicile Luxembourg, "
        "replication Swap based Unfunded, currency-hedged, fund size 87 M EUR"
    ) in line


def test_a_fund_the_catalogue_cannot_describe_says_its_cost_is_not_known(client, monkeypatch):
    _load_catalogue(client, monkeypatch)
    _hold(client, NO_ISIN, OUTSIDE)

    with SessionLocal() as db:
        analyst = advisor.build_portfolio_context(db)

    assert "; TER not known: no ISIN is recorded for it" in _line(analyst, "Fondo Senza Codice")
    assert (
        "; ISIN IE000NOTHER9, TER not known: the fund catalogue does not hold it"
    ) in _line(analyst, "Fondo Fuori Elenco")
    assert 'The facts after "catalogue:"' not in analyst, "nothing was described"


def test_an_empty_catalogue_says_so_instead_of_a_cost(client):
    _hold(client, WORLD)

    with SessionLocal() as db:
        line = _line(advisor.build_portfolio_context(db), "Esempio World")

    assert (
        "; ISIN IE000EXMPL01, TER not known: the fund catalogue has not been downloaded yet"
    ) in line


def test_a_share_is_given_no_cost_at_all(client, monkeypatch):
    """A TER does not apply to a share: "not known" would claim one exists."""
    _load_catalogue(client, monkeypatch)
    _hold(client, SHARE)

    with SessionLocal() as db:
        line = _line(advisor.build_portfolio_context(db), "Azione Esempio")

    assert "TER" not in line and "ISIN" not in line


def test_the_chat_reads_the_same_fund_lines(client, monkeypatch):
    _load_catalogue(client, monkeypatch)
    _hold(client, WORLD, NO_ISIN)

    with SessionLocal() as db:
        picture = advisor.build_context(db)
        analyst = advisor.build_portfolio_context(db)

    for name in ("Esempio World", "Fondo Senza Codice"):
        assert _line(picture, name) == _line(analyst, name)
    assert "TER 0.17% a year" in _line(picture, "Esempio World")
    assert 'The facts after "catalogue:"' in picture


def test_the_portfolio_page_is_not_sent_the_isin(client, monkeypatch):
    """The ISIN joins the rows to reach the catalogue; the page's payload
    stays as its schema declares it."""
    _load_catalogue(client, monkeypatch)
    _hold(client, WORLD)

    rows = client.get("/api/dashboard/portfolio").json()["rows"]
    assert rows and all("isin" not in row for row in rows)


# --- The rules, in the prompts --------------------------------------------------------


def test_the_analyst_never_quotes_a_fund_cost_from_memory():
    prompt = advisor.PORTFOLIO_SYSTEM_PROMPT
    assert "are the catalogue's, on the fund's line" in prompt
    assert "Never quote a fund's cost from memory." in prompt


def test_the_confidant_raises_a_stated_figure_as_a_question():
    prompt = chain.CONFIDANT_SYSTEM_PROMPT
    assert "Their answers are dated" in prompt
    assert "do not correct the figure with it: raise it as a question to ask them" in prompt


def test_the_revision_holds_the_record_against_a_stated_figure():
    prompt = chain.REVISION_SYSTEM_PROMPT
    assert "Nor can something the person said." in prompt
    assert "HOLD the recorded figure, name the conflict" in prompt
    assert "never the headline" in prompt


def test_the_synthesis_gives_the_recorded_figure_and_what_to_check():
    prompt = chain.SYNTHESIS_SYSTEM_PROMPT
    assert "the recorded figure is the one you give, with the open question beside it" in prompt
    assert "Never tell them to enter what may already be there: tell them what to check." in prompt


@pytest.mark.parametrize(
    "prompt",
    [advisor.PORTFOLIO_SYSTEM_PROMPT, chain.CONFIDANT_SYSTEM_PROMPT,
     chain.REVISION_SYSTEM_PROMPT, chain.SYNTHESIS_SYSTEM_PROMPT],
    ids=["analyst", "confidant", "revision", "synthesis"],
)
def test_each_new_rule_is_written_without_a_dash(prompt):
    rules = [
        s for s in prompt.split(". ")
        if any(k in s for k in ("catalogue's", "answers are dated", "something the person said",
                                "recorded figure", "what may already be there"))
    ]
    assert rules
    for rule in rules:
        assert chr(0x2014) not in rule and f" {chr(0x2013)} " not in rule
