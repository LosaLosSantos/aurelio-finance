"""A gap in the records is no reason to propose a fresh analysis.

The reader's test round, 2026-10-08 (read by the reviewer): the chat put up
`run_analysis`'s card while the last analysis was current, justified by
household costs nobody had recorded. The analysis reads the same records, so
it would not have seen them either. Brief BE, on the reader's word: one
sentence in the system prompt, beside the rule for when to propose one. It
is not measured on the wire: a paid turn would measure one answer.
"""

from __future__ import annotations

from app import chat


def test_the_prompt_says_a_gap_is_no_reason_for_a_fresh_analysis():
    rule = chat.SYSTEM_PROMPT.split("`run_analysis` is the one that is not about their records.")[1]
    rule = rule.split("\n\n")[0]
    assert (
        "A gap in the records is no reason for a fresh one: it reads the same records and "
        "would not see it either; say what is missing and where it is entered."
    ) in rule
