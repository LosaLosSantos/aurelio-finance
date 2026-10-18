"""A routing variant of a model OpenRouter serves is not a model that is gone.

OpenRouter's page on model variants (read 2026-10-17) names two kinds of
suffix. A routing variant (`:nitro`, `:floor`, `:exacto`, `:online`) is
accepted on any model at request time and is never an entry of the public
list; a catalog variant (`:free`, `:batch`, `:thinking`, `:extended`) is an
entry of its own, and a name carrying one the list lacks does not fall back to
its base. The entry that describes a name is its base slug and its catalog
variant, the routing variants dropped.

`2ba7466` searched the list for the name as written. Measured at `2be2ddb`
(brief BB's P0, offline, OpenRouter faked at the transport): with
`OPENROUTER_MODEL=anthropic/claude-sonnet-4.6:nitro` and that model listed, a
400 read "The model anthropic/claude-sonnet-4.6:nitro is no longer served by
OpenRouter: ... its public list of models no longer has it."

The fakes are `test_a_model_that_is_gone.py`'s: the real `stream_llm` and
`call_llm`, the transport inside the real client faked, and the public list.
"""

from __future__ import annotations

import pytest

from app import advisor
from tests.test_a_model_that_is_gone import (  # noqa: F401 (fixtures)
    _analysis_error,
    _chat_error,
    openrouter,
    public_list,
)

SERVED = "anthropic/claude-sonnet-4.6"
REFUSED = (400, {"error": {"code": 400, "message": "Provider returned error"}})


@pytest.mark.parametrize("suffix", [":nitro", ":floor", ":exacto", ":online", ":nitro:exacto"])
def test_a_refused_routing_variant_of_a_listed_model_is_not_called_gone(
    client, openrouter, public_list, monkeypatch, suffix
):
    monkeypatch.setenv("OPENROUTER_MODEL", SERVED + suffix)
    openrouter.answer = REFUSED

    sentence = _chat_error(client)

    assert sentence.startswith(f"OpenRouter refused the call to {SERVED}{suffix} with 400: "), sentence
    assert "OpenRouter said: Provider returned error." in sentence
    assert "no longer served" not in sentence
    assert public_list.asked == 1


def test_an_analysis_on_a_routing_variant_of_a_listed_model_is_not_called_gone(
    openrouter, public_list, monkeypatch
):
    monkeypatch.setenv("OPENROUTER_MODEL", SERVED + ":floor")
    openrouter.answer = REFUSED

    sentence = _analysis_error()

    assert sentence.startswith(f"OpenRouter refused the call to {SERVED}:floor with 400: "), sentence
    assert "no longer served" not in sentence


def test_a_gone_model_written_with_a_routing_variant_still_names_its_dated_versions(
    client, openrouter, public_list, monkeypatch
):
    monkeypatch.setenv("OPENROUTER_MODEL", "qwen/qwen3.8-max:nitro")

    sentence = _chat_error(client)

    assert sentence.startswith("The model qwen/qwen3.8-max:nitro is no longer served by OpenRouter"), sentence
    assert "OpenRouter still lists qwen/qwen3.8-max-0902, a dated version of it." in sentence


def test_a_catalog_variant_the_list_lacks_is_gone_and_does_not_fall_back(
    client, openrouter, public_list, monkeypatch
):
    # The base is listed and its `:free` entry is not: OpenRouter routes such a
    # name nowhere, and says so in the page this rule comes from.
    monkeypatch.setenv("OPENROUTER_MODEL", "qwen/qwen3.8-max-0902:free")

    sentence = _chat_error(client)

    assert sentence.startswith("The model qwen/qwen3.8-max-0902:free is no longer served by OpenRouter"), sentence


def test_a_listed_catalog_variant_with_a_routing_one_is_not_called_gone(
    client, openrouter, public_list, monkeypatch
):
    public_list.ids = public_list.ids | {"poolside/laguna-s-2.1:free"}
    monkeypatch.setenv("OPENROUTER_MODEL", "poolside/laguna-s-2.1:free:nitro")
    openrouter.answer = REFUSED

    sentence = _chat_error(client)

    assert sentence.startswith("OpenRouter refused the call to poolside/laguna-s-2.1:free:nitro with 400: ")
    assert "no longer served" not in sentence


@pytest.mark.parametrize(
    "written, entry",
    [
        # OpenRouter's own examples, from its page on model variants.
        ("openai/gpt-5.2:nitro", "openai/gpt-5.2"),
        ("openai/gpt-5.2:nitro:exacto", "openai/gpt-5.2"),
        ("poolside/laguna-s-2.1:free", "poolside/laguna-s-2.1:free"),
        ("poolside/laguna-s-2.1:free:nitro", "poolside/laguna-s-2.1:free"),
        # A routing variant before the catalog one is dropped all the same.
        ("poolside/laguna-s-2.1:nitro:free", "poolside/laguna-s-2.1:free"),
        ("google/gemini-2.5-pro:batch", "google/gemini-2.5-pro:batch"),
        # No suffix, and one the page does not name, which is no variant.
        ("anthropic/claude-opus-5.5", "anthropic/claude-opus-5.5"),
        ("~anthropic/claude-opus-latest", "~anthropic/claude-opus-latest"),
        ("some/model:beta", "some/model:beta"),
    ],
)
def test_the_entry_of_a_name_is_its_base_and_its_catalog_variant(written, entry):
    assert advisor.catalog_id(written) == entry
