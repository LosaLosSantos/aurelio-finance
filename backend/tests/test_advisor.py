"""What the model is given, and the chain that argues over it.

There are no analysis endpoints any more: the two single-shot analyses are
gone, and the chain is a tool the chat proposes rather than a page with a
button. So this file tests the two things left in `advisor.py` — the contexts
it builds and the asymmetry between them — and `chain.py`, driven directly.

`advisor.call_llm` is monkeypatched everywhere. Nothing here reaches
OpenRouter, and the chain is now a variable number of calls, so the fakes
script the CONFIDANT's verdict line: that line is what decides how many calls
there are, and a fake that always says the same thing would only ever exercise
one depth.
"""

from __future__ import annotations

import pytest

from app import advisor, chain, chat, models
from app.database import SessionLocal

# The real call, captured at import time — before the autouse `offline` fixture
# replaces the module attribute with a refusal — so the one test about what it
# reads off a completion can still reach the genuine article.
_REAL_CALL_LLM = advisor.call_llm


def test_build_context_includes_ledger_and_position_economics(client):
    """The LLM context must show projected positions (avg cost, realized P/L),
    the transaction ledger, and each PAC's execution status."""
    import datetime

    from app import advisor
    from app.database import SessionLocal

    today = datetime.date.today().isoformat()
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2020-01-10"}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )
    client.post(
        "/api/transactions",
        json={"date": today, "institution_id": iid, "asset_name": "Vanguard All-World",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 120, "currency": "EUR", "price_currency": "EUR"},
    )
    client.post(
        "/api/transactions",
        json={"kind": "sell", "date": today, "institution_id": iid,
              "asset_name": "Vanguard All-World", "symbol": "VWCE.MI",
              "quantity": 5, "unit_price": 130, "currency": "EUR", "price_currency": "EUR"},
    )
    client.post(
        "/api/accumulation-plans",
        json={"name": "PAC All-World", "amount": 800, "currency": "EUR", "frequency": "monthly",
              "start_date": today, "source_institution_id": iid,
              "targets": [{"symbol": "VWCE.MI", "institution_id": iid}]},
    )

    with SessionLocal() as db:
        ctx = advisor.build_context(db)

    assert "avg cost 110.00" in ctx          # (1000 + 1200) / 20
    assert "realized P/L +100.00" in ctx     # 650 - 5*110
    assert "## Transaction ledger" in ctx
    assert f"{today} sell 5 x VWCE.MI @ 130.00" in ctx
    assert "no executions recorded yet" in ctx


def test_build_portfolio_context_has_the_look_through_and_no_personal_data(client, monkeypatch):
    """The unbiased context must contain the look-through but NO personal data.
    It is no longer investments only (since brief Z it carries the money beside
    them: test_the_analysis_sees_the_money.py), and still nothing of the person."""
    import datetime

    from app import composition
    from app.database import SessionLocal

    today = datetime.date.today().isoformat()
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": today}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "VWCE", "asset_class": "fund_etf", "symbol": "VWCE.MI",
              "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )
    # personal data that must NOT leak into the portfolio context
    client.put(
        "/api/survey",
        json=[{"question_key": "about_age", "topic": "About you",
               "question": "Your age?", "answer": "31"}],
    )
    # VWCE.MI is a fund, so the equity probe finds nothing and the waterfall
    # goes looking for holdings. Said here rather than left to the boundary
    # refusing: "this is not a share" and "nobody answered" are different
    # facts, and only the first one is what this test is standing on.
    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda s: None)
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {"VWCE": "IE00BK5BQT80"})
    monkeypatch.setattr(
        composition, "_fetch_issuer", lambda i: (_ for _ in ()).throw(RuntimeError("no adapter"))
    )
    monkeypatch.setattr(
        composition,
        "_fetch_justetf",
        lambda isin: {
            "name": "Vanguard FTSE All-World",
            "countries": [{"name": "United States", "pct": 60.0}],
            "sectors": [{"name": "Technology", "pct": 30.0}],
            "top_holdings": [], "holdings_count": 3768,
        },
    )

    with SessionLocal() as db:
        ctx = advisor.build_portfolio_context(db)

    assert "United States: 60.00%" in ctx
    assert "Coverage: 100.0%" in ctx
    assert "31" not in ctx and "About you" not in ctx  # no personal context


def test_both_contexts_describe_a_position_in_the_same_words(client):
    """The position block was written out twice and the two copies had already
    drifted — one printed the price it valued the row at, the other only the
    date; one said "dividends collected", the other "dividends". They share one
    renderer now, so the full picture and the analyst cannot disagree about the
    same row, and neither can quietly become the stale copy."""
    import datetime

    from app.database import SessionLocal

    today = datetime.date.today().isoformat()
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2020-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100,
              "cost_basis": 900, "currency": "EUR"},
    )
    client.post(
        "/api/transactions",
        json={"kind": "dividend", "date": today, "institution_id": iid,
              "asset_name": "Vanguard All-World", "symbol": "VWCE.MI",
              "quantity": 10, "unit_price": 2, "currency": "EUR", "price_currency": "EUR"},
    )

    with SessionLocal() as db:
        full = advisor.build_context(db)
        analyst = advisor.build_portfolio_context(db)

    def position_line(ctx: str) -> str:
        return next(ln for ln in ctx.splitlines() if ln.startswith("- Vanguard All-World"))

    def totals(ctx: str) -> list[str]:
        # The position block's totals. Since brief Z the analyst's context also
        # totals the cash and the debts beside the investments, which are not
        # lines the shared renderer writes.
        return [
            ln for ln in ctx.splitlines()
            if ln.startswith("- TOTAL") and not ln.startswith(("- TOTAL cash", "- TOTAL debts"))
        ]

    assert position_line(full) == position_line(analyst)
    assert "dividends collected 20.00" in position_line(full)
    assert totals(full) == totals(analyst)


def test_an_unanswered_question_is_not_an_answer(client):
    """The two survey blocks disagreed about blanks: one printed every row, so
    a question the user skipped arrived as "- Your age?: None" — which reads to
    a model as something they said. The shared renderer drops unanswered rows,
    and the topic heading with them when nothing is left under it."""
    from app import crud
    from app.database import SessionLocal

    client.put(
        "/api/survey",
        json=[
            {"question_key": "about_age", "topic": "About you",
             "question": "Your age?", "answer": "31"},
            {"question_key": "self_narrative", "topic": "In your words",
             "question": "Tell us about yourself", "answer": None},
        ],
    )

    with SessionLocal() as db:
        rendered = advisor._render_survey(crud.get_survey_responses(db))
        contexts = [advisor.build_context(db), advisor.build_person_context(db)]

    assert not any(ln.endswith(": None") for ln in rendered)
    for ctx in contexts:
        assert "Your age?: 31" in ctx
        assert "Tell us about yourself" not in ctx
        assert "In your words" not in ctx  # no heading over a topic with nothing in it


def test_an_undated_picture_says_so_instead_of_printing_None(client):
    """The fourth copy of the same defect, two functions below the survey one:
    "- As of: None" reads to a model as a value, not as an absence. The screen
    already drops the clause when nothing is dated (Dashboard.tsx); the advisor
    was again the only reader left to guess."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        empty = advisor.build_context(db)
    assert "As of: None" not in empty
    assert "- As of: no situation, valuation or balance on record yet" in empty

    # and a real photograph still dates the picture
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )
    with SessionLocal() as db:
        dated = advisor.build_context(db)
    assert "- As of: 2026-01-10" in dated


# --- The advisor chain ------------------------------------------------------


def _fake_chain_calls(monkeypatch, confidant=("FITS",)):
    """Record every LLM call the chain makes and answer with the role's name.

    `confidant` is the verdict line each confidant turn ends on, in order — the
    one thing in a reply that changes how many more calls there are. The last
    entry repeats, so `("CONTESTED",)` is a colleague that never gives up and
    the bound is what stops it.
    """
    seen: list[dict] = []
    verdicts = list(confidant)

    def fake(system_prompt, user_content, model=None):
        seen.append({"system": system_prompt, "user": user_content, "model": model})
        text = f"output-{len(seen)}"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            said = verdicts[min(sum(1 for c in seen if c["system"] == system_prompt) - 1,
                                len(verdicts) - 1)]
            text += f"\n\nVERDICT: {said}"
        return {"analysis": text, "model": model or "default/model", "cost": 0.002}

    monkeypatch.setattr(advisor, "call_llm", fake)
    return seen


def _run(db):
    """Drive `run_chain` to its end. Returns (the steps it announced, the run)."""
    walk = chain.run_chain(db)
    announced = []
    while True:
        try:
            announced.append(next(walk))
        except StopIteration as done:
            return announced, done.value


def test_a_challenge_nobody_contests_costs_three_calls_not_four(client, monkeypatch):
    """The point of an orchestrator over a pipeline. The analyst and the
    confidant are the asymmetry and cannot be cut; the synthesis is the only
    thing written to the person. The revision is the one that is worth its wait
    only when there is something to answer — and the confidant, whose mandate
    already tells it to wave a fitting finding through in one line, is the one
    that knows."""
    seen = _fake_chain_calls(monkeypatch, confidant=("FITS",))
    with SessionLocal() as db:
        announced, run = _run(db)
        assert len(seen) == 3
        assert [s.role for s in announced] == ["analyst", "confidant", "synthesis"]
        assert [s.role for s in run.steps] == ["analyst", "confidant", "synthesis"]
        assert [s.step_no for s in run.steps] == [1, 2, 3]
        assert run.verdict.startswith("output-3")


def test_a_contested_challenge_buys_the_round_it_is_worth(client, monkeypatch):
    """Contested once, then satisfied: the analyst answers, the colleague reads
    the answer rather than the original findings, and the run stops there."""
    seen = _fake_chain_calls(monkeypatch, confidant=("CONTESTED", "FITS"))
    with SessionLocal() as db:
        _, run = _run(db)
        assert [s.role for s in run.steps] == [
            "analyst",
            "confidant",
            "revision",
            "confidant",
            "synthesis",
        ]
    # the second challenge read the REVISION, not the findings again
    second_challenge = [c for c in seen if c["system"] == chain.CONFIDANT_SYSTEM_PROMPT][1]
    assert "output-3" in second_challenge["user"]
    assert "The analyst's answer" in second_challenge["user"]


def test_an_argument_that_never_ends_is_ended(client, monkeypatch):
    """Deeper where depth earns it, and bounded because the third round of the
    same argument is two models restating themselves at the reader's expense.
    The bound is a number somebody chose, not a model's stamina."""
    _fake_chain_calls(monkeypatch, confidant=("CONTESTED",))
    with SessionLocal() as db:
        _, run = _run(db)
        assert sum(1 for s in run.steps if s.role == "revision") == chain.MAX_REVISION_ROUNDS
        assert len(run.steps) == chain.MAX_STEPS
        assert run.steps[-1].role == "synthesis"


def test_a_confidant_that_forgets_to_say_is_answered_anyway(client, monkeypatch):
    """The step is cut when the confidant SAYS it is not needed, and at no other
    time. A reply with no marker is a formatting slip, and cutting the depth of
    an analysis on a formatting slip is the wrong direction to fail in."""
    seen: list[dict] = []

    def no_marker(system_prompt, user_content, model=None):
        seen.append({"system": system_prompt})
        return {"analysis": f"output-{len(seen)}", "model": model, "cost": None}

    monkeypatch.setattr(advisor, "call_llm", no_marker)
    with SessionLocal() as db:
        _, run = _run(db)
        assert any(s.role == "revision" for s in run.steps)


@pytest.mark.parametrize(
    "reply, contested",
    [
        ("...\n\nVERDICT: FITS", False),
        ("...\n\n**VERDICT: FITS**", False),
        ("...\n\nVERDICT: CONTESTED", True),
        ("I might end with VERDICT: FITS\n\nVERDICT: CONTESTED", True),
        ("no marker at all", True),
        ("VERDICT: fits", False),
    ],
)
def test_the_last_word_is_the_one_that_counts(reply, contested):
    """A model that discusses its own marker mid-text has not changed its mind
    by mentioning it, and markdown around the line does not change what it
    says."""
    assert chain.contested(reply) is contested


@pytest.mark.parametrize(
    "reply, verdict",
    [
        ("...\n\nVERDICT: CONTESTED", chain.CONTESTED),
        ("...\n\n**VERDICT: FITS**", chain.FITS),
        ("VERDICT: fits", chain.FITS),
        ("no marker at all", None),
        ("VERDICT: probably fine", None),
    ],
)
def test_a_confidant_that_said_nothing_is_not_a_confidant_that_said_no(reply, verdict):
    """The same line, read once, answering three ways — and the two callers
    disagree about the third on purpose.

    `contested` decides whether to buy another round, and there a missing
    marker has to mean "argue": cutting the depth of an analysis because a
    model forgot to format a line is failing in the wrong direction. A COUNT of
    how often the mandate actually bites is the opposite case — a run nobody
    marked says nothing about whether the confidant is doing its job, and
    folding it into either column would be inventing the answer to the only
    question the count exists to ask.
    """
    assert chain.verdict_of(reply) == verdict
    assert chain.contested(reply) is (verdict != chain.FITS)


def test_the_runs_can_be_listed_and_each_one_says_whether_it_argued(client, monkeypatch):
    """The listing the app had no way to produce about runs it could already
    address by id. Without it, a run whose card had scrolled out of a
    conversation — or whose conversation was deleted — stayed perfectly well
    stored and completely unreachable.

    What each row carries is the confidant's own verdict, which is what turns
    "is this chain actually adversarial or is it theatre?" from an impression
    into a count.
    """
    _fake_chain_calls(monkeypatch, confidant=("FITS",))
    with SessionLocal() as db:
        _, quiet = _run(db)
        quiet_id = quiet.id
    _fake_chain_calls(monkeypatch, confidant=("CONTESTED", "FITS"))
    with SessionLocal() as db:
        _, argued = _run(db)
        argued_id = argued.id

    rows = client.get("/api/advisor/chain").json()
    assert [r["id"] for r in rows] == [argued_id, quiet_id], "newest first"
    assert [r["challenge"] for r in rows] == ["contested", "fits"]
    assert [r["step_count"] for r in rows] == [5, 3]
    assert [r["revisions"] for r in rows] == [1, 0]
    assert all(r["created_at"] for r in rows)
    # No text: the verdict is a document and the steps are four more of them.
    assert "verdict" not in rows[0] and "output" not in str(rows[0])


def test_a_run_that_argued_to_the_last_round_is_still_a_run_that_argued(client, monkeypatch):
    """Where counting steps would lie in the first direction. The confidant
    contests every time, `MAX_REVISION_ROUNDS` stops the loop on a revision, so
    the LAST word in the record is the analyst's and no further revision was
    bought — but the mandate bit, every round, and the marker says so."""
    _fake_chain_calls(monkeypatch, confidant=("CONTESTED",))
    with SessionLocal() as db:
        _run(db)

    row = client.get("/api/advisor/chain").json()[0]
    assert row["challenge"] == "contested"
    assert row["revisions"] == chain.MAX_REVISION_ROUNDS
    assert row["step_count"] == chain.MAX_STEPS


def test_a_run_nobody_marked_is_counted_as_neither(client, monkeypatch):
    """And where counting steps would lie in the other direction. A confidant
    that never formatted the line bought every revision round it could — depth
    that looks exactly like a fierce argument — while saying nothing at all
    about whether it was one. The row reports the depth and refuses the verdict,
    because a count of an adversarial mandate that quietly counted silence
    would be measuring its own default."""

    def no_marker(system_prompt, user_content, model=None):
        return {"analysis": "said nothing about it", "model": "m", "cost": None}

    monkeypatch.setattr(advisor, "call_llm", no_marker)
    with SessionLocal() as db:
        _run(db)

    row = client.get("/api/advisor/chain").json()[0]
    assert row["challenge"] == "unstated"
    assert row["revisions"] == chain.MAX_REVISION_ROUNDS


def test_the_history_is_a_readers_surface_and_not_a_sub_agents_context(client, monkeypatch):
    """The constraint that outranks the feature.

    The analyst sees the portfolio and not the person; the confidant sees the
    person and not one figure. A past run is the one document in this app that
    contains BOTH — the findings and the challenge, side by side — so handing a
    later run its own history would dissolve the asymmetry from the inside,
    quietly, while every existing test about who reads what still passed.

    The chat is not a sub-agent and always could read it: it is the reader's
    own assistant over the reader's own picture. The line is between it and the
    two blind roles, and this is where that line is asserted.
    """
    _fake_chain_calls(monkeypatch, confidant=("CONTESTED", "FITS"))
    with SessionLocal() as db:
        _, first = _run(db)
        run_id, verdict = first.id, first.verdict

        assert f"Run {run_id}" in chat.build_chat_context(db)
        blind = [advisor.build_portfolio_context(db), advisor.build_person_context(db)]

    for context in blind:
        assert f"Run {run_id}" not in context
        assert verdict not in context

    # and a second run is told nothing about the first
    seen = _fake_chain_calls(monkeypatch, confidant=("FITS",))
    with SessionLocal() as db:
        _run(db)
    assert seen, "the second run made no calls at all"
    assert all(verdict not in call["user"] for call in seen)


def test_every_finished_step_is_announced_before_anything_is_saved(client, monkeypatch):
    """What the old page refused to fake. `run_chain` still writes nothing until
    all of it has finished — a half-run chain must not reach the reader — but
    that is a rule about what is SAVED, and a step that has finished is a fact
    either way."""
    _fake_chain_calls(monkeypatch, confidant=("FITS",))
    with SessionLocal() as db:
        walk = chain.run_chain(db)
        first = next(walk)
        assert first.step_no == 1 and first.role == "analyst"
        assert first.title == "The numbers, on their own merits"
        assert first.duration_ms is not None
        assert db.query(models.ChainRun).count() == 0, "it saved a half-run chain"
        for _ in walk:
            pass
        assert db.query(models.ChainRun).count() == 1


def test_the_chain_keeps_the_information_asymmetry(client, monkeypatch):
    """The analyst must not see the person, and the confidant must not see the
    portfolio figures — that asymmetry is the whole point of the chain, and the
    chat orchestrating it changes nothing about who reads what. Nothing about
    the look-through is faked here on purpose: this test is about who sees what,
    and the offline boundary makes "no source answered" the same answer on every
    run.
    """
    client.put(
        "/api/survey",
        json=[
            {
                "question_key": "self_narrative",
                "topic": "In your words",
                "question": "Tell us about yourself",
                "answer": "I panic when markets drop and I want plain language.",
            }
        ],
    )
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )

    seen = _fake_chain_calls(monkeypatch, confidant=("CONTESTED", "FITS"))
    with SessionLocal() as db:
        _run(db)

    analyst = seen[0]
    assert "Vanguard All-World" in analyst["user"]
    assert "I panic" not in analyst["user"]  # blind to the person
    for challenge in [c for c in seen if c["system"] == chain.CONFIDANT_SYSTEM_PROMPT]:
        assert "I panic" in challenge["user"]
        assert "1000" not in challenge["user"]  # blind to the figures, every round
    # the confidant's mandate has to be adversarial, or the chain is theatre
    assert "ADVERSARIAL" in chain.CONFIDANT_SYSTEM_PROMPT
    assert "REVISE" in chain.REVISION_SYSTEM_PROMPT
    assert "HOLD" in chain.REVISION_SYSTEM_PROMPT


def test_the_chain_uses_per_role_models_when_configured(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", "moonshotai/kimi-k3")
    monkeypatch.setenv("OPENROUTER_CONFIDANT_MODEL", "anthropic/claude-sonnet-4.6")
    seen = _fake_chain_calls(monkeypatch, confidant=("CONTESTED", "FITS"))
    with SessionLocal() as db:
        _run(db)
    assert [s["model"] for s in seen] == [
        "moonshotai/kimi-k3",       # analyst
        "anthropic/claude-sonnet-4.6",  # confidant
        "moonshotai/kimi-k3",       # revision — the same analyst
        "anthropic/claude-sonnet-4.6",  # confidant again
        "anthropic/claude-sonnet-4.6",  # synthesis, written to the person
    ]


def test_a_chain_that_fails_saves_nothing(client, monkeypatch):
    """A half-run chain is never saved, so the reader never sees a verdict that
    skipped its own critique — and the steps announced before the failure were
    true when they were said, which is why none of them is a record."""
    calls = {"n": 0}

    def flaky(system_prompt, user_content, model=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise advisor.AdvisorError("LLM call failed: boom")
        return {"analysis": "ok", "model": "m", "cost": None}

    monkeypatch.setattr(advisor, "call_llm", flaky)
    with SessionLocal() as db:
        with pytest.raises(advisor.AdvisorError):
            _run(db)
        assert db.query(models.ChainRun).count() == 0


def test_what_a_step_cost_is_recorded_and_not_estimated(client, monkeypatch):
    """The figure the confirmation card quotes has to be a measurement. It was
    on the wire all along — OpenRouter reports it on the final chunk's usage —
    and nothing in the repo kept it."""
    _fake_chain_calls(monkeypatch, confidant=("FITS",))
    with SessionLocal() as db:
        _, run = _run(db)
        assert [s.cost for s in run.steps] == [0.002, 0.002, 0.002]
        run_id = run.id

    body = client.get(f"/api/advisor/chain/{run_id}").json()
    assert [s["cost"] for s in body["steps"]] == [0.002, 0.002, 0.002]
    assert body["verdict"].startswith("output-3")
    assert client.get("/api/advisor/chain/999").status_code == 404


def test_a_provider_that_reports_no_price_leaves_it_empty_not_zero(monkeypatch):
    """`call_llm` reads the cost off `usage` with getattr, because it is an
    extra field the OpenAI SDK does not declare. A zero would be a price."""

    class FakeCompletion:
        # finish_reason because a real choice always says how the answer
        # ended, and `call_llm` refuses one that ended on anything but a stop.
        def __init__(self, usage):
            message = type("M", (), {"content": "hello"})()
            self.choices = [type("C", (), {"message": message, "finish_reason": "stop"})()]
            self.usage = usage

    def client_with(usage):
        class FakeCompletions:
            def create(self, **kwargs):
                return FakeCompletion(usage)

        return type("C", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})()

    monkeypatch.setattr(advisor, "_client", lambda: client_with(
        type("U", (), {"cost": 0.00225})()
    ))
    assert _REAL_CALL_LLM("s", "u", model="m")["cost"] == 0.00225

    monkeypatch.setattr(advisor, "_client", lambda: client_with(type("U", (), {})()))
    assert _REAL_CALL_LLM("s", "u", model="m")["cost"] is None

    monkeypatch.setattr(advisor, "_client", lambda: client_with(None))
    assert _REAL_CALL_LLM("s", "u", model="m")["cost"] is None
