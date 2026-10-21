"""No em dash, and no en dash between spaces, in what the chat's model reads
or a card shows.

The standing rule names the chat's context beside every page: no em dash in
anything the reader sees. Brief AG took them out of the chat's prompt, the
tools' descriptions and the readings. Measured at `c61e5bc` (brief BE), two
were still on screen, in the titles of a close's and a dividend's cards
(`tools._propose_transaction`), and eleven in the picture: the tax line, a
currency mismatch's note and a corrected dividend's (`advisor.py`), the last
analysis's line (`chat.py`), and seven of the pages' notes (`screen.py`).

Read in the source, every string but the docstrings, so a new one is caught
where it is written. The one exception is the rule itself, which names both
characters to forbid them.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
EM, EN = chr(0x2014), chr(0x2013)
# The system prompt's own sentence forbidding both, which must name them.
THE_RULE = "Never write an em dash ("


def _strings(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


@pytest.mark.parametrize("module", ["advisor.py", "chat.py", "screen.py", "tools.py"])
def test_no_string_the_chat_reads_carries_a_dash(module):
    dashed = [
        (line, text[:80])
        for line, text in _strings(APP / module)
        if (EM in text or f" {EN} " in text) and not text.startswith(THE_RULE)
    ]
    assert dashed == []
