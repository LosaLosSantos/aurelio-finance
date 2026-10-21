"""An answer that did not finish goes back to the model with the line the
reader saw under it.

Brief Z, 2026-10-02: `chat._wire` replays every stored answer's words
whatever its ending, so a cut or broken answer reached the model on the next
question as its own words, with nothing saying they stopped. Measured at
`c61e5bc` (brief BE): "partial answer " went back as it was, pinned so by
`test_a_reader_who_leaves_leaves_a_cut_answer_on_record`. The panel shows a
line under such an answer (`ChatPanel.tsx`, `EndNote`); the model now reads
the same line, in brackets after the words, and an answer that finished goes
back as before. Every text here is invented.
"""

from __future__ import annotations

import json

from app import advisor, chat


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(f.split("\n")[1][len("data: "):]) for f in response.text.strip().split("\n\n")]


def _model(monkeypatch, pieces=("Fine.",), fail_after: int | None = None) -> list[list[dict]]:
    asked: list[list[dict]] = []

    def stream(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        asked.append(list(messages))
        for i, piece in enumerate(pieces):
            if fail_after is not None and i == fail_after:
                raise advisor.AdvisorError("LLM stream failed: connection reset")
            yield ("text", piece)

    monkeypatch.setattr(advisor, "stream_llm", stream)
    return asked


def _ask(client, content: str, conversation_id: int | None = None) -> list[dict]:
    return _events(client.post("/api/chat", json={"content": content, "conversation_id": conversation_id}))


def test_a_broken_answer_goes_back_with_its_sentence(client, monkeypatch):
    _model(monkeypatch, pieces=("Your cash is ", "spread over ", "two accounts."), fail_after=2)
    first = _ask(client, "Where is my cash?")
    assert [e["kind"] for e in first][-1] == "error"
    asked = _model(monkeypatch)

    _ask(client, "Go on", first[0]["conversation_id"])

    assert asked[0][-2] == {
        "role": "assistant",
        "content": "Your cash is spread over \n\n[LLM stream failed: connection reset]",
    }


def test_an_answer_that_finished_goes_back_as_it_was(client, monkeypatch):
    _model(monkeypatch, pieces=("Your cash is on two accounts.",))
    first = _ask(client, "Where is my cash?")
    asked = _model(monkeypatch)

    _ask(client, "Thanks", first[0]["conversation_id"])

    assert asked[0][-2] == {"role": "assistant", "content": "Your cash is on two accounts."}


def test_an_answer_cut_after_a_call_ends_on_its_own_line():
    """Cut after a lookup came back: the line follows the call's answer, as an
    assistant turn of its own, since the words before the call are not the
    last thing that answer did."""
    blocks = [
        {"kind": "text", "text": "Let me look."},
        {"kind": "tool", "name": "get_look_through", "ok": True, "detail": None,
         "call_id": "call_7", "arguments": {}},
    ]

    out = chat._answer_on_the_wire(5, blocks, chat.STOPPED)

    assert [m["role"] for m in out] == ["assistant", "tool", "assistant"]
    assert out[0]["content"] == "Let me look."
    assert out[-1] == {"role": "assistant", "content": "[Stopped before it was finished.]"}
