"""Asked whether something is worth buying, and how much, the chat answers as
one evaluation.

Brief AQ (2026-10-12). In the brief's P0, three scouting questions (a share,
a UCITS ETF, a commodity) ran one web search between them, none about the
share or the ETF; the look-through was read once; every amount was the
model's arithmetic. The prompt now says what the answer is made of and in
which order: what the instrument is, read and never recalled; how it fits
them, from `size_purchase`; a verdict that says what it rests on; how much,
within the figures; then the card, or the reason there is none. A model
offered the web is told, beside the tool that searches, to search what the
instrument is doing before the verdict. Whether the model does so is P1's to
measure; these pin what it is told.
"""

from __future__ import annotations

from app import chat, tools

OPUS = "claude-opus-5.5"
EVALUATION = (
    "When they ask whether something is worth buying for them, and how much, answer it as "
    "one evaluation, in this order. What it is, read and never recalled: for a fund, what the "
    "catalogue says of it (its domicile, its cost, what it does with dividends, how it holds "
    "what it tracks); for a share, its listing and the currency Yahoo quotes it in. How it "
    "fits them: `size_purchase` with the instrument and the sum you weigh, for what it would "
    "weigh in their investments, in a region, a sector, a company and a currency, and what "
    "they already hold of it through their funds. A verdict that says what it rests on: their "
    "records, those figures, and what you do not know. How much: within the figures "
    "`size_purchase` gives, with what you assumed. Then the card, carrying that amount; when "
    "the verdict is no, the reason, and no card."
)
SEARCH_IT = (
    "and, before the verdict on an instrument they ask about buying, what it is doing (its "
    "results, valuation, risks and news)"
)


def test_every_model_is_told_the_shape_of_the_evaluation():
    for prompt in (chat.SYSTEM_PROMPT, chat.system_prompt(OPUS)):
        assert EVALUATION in prompt
        # Beside the card it ends on, where a capability is said beside its tool.
        assert prompt.index(EVALUATION) < prompt.index("`suggest_instrument` is the only one")


def test_a_model_offered_the_web_is_told_to_search_what_the_instrument_is_doing():
    """Beside the tool that searches, in its declaration, which only a model
    offered the web receives; the web's rules stay as short as brief AM held
    them, since they go out on every turn."""
    (declared,) = tools.web_search(OPUS)
    assert SEARCH_IT in declared["function"]["description"]
    assert tools.web_search("unsupported-model") == []
    assert len(chat.WEB_RULES) < 1000
