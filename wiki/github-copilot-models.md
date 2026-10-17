---
title: "Use Aurelio with GitHub Copilot"
description: "Authenticate GitHub Copilot, choose models for Aurelio's chat and analysis, and understand what financial context leaves the computer."
parent: "Guides"
nav_order: 2
---

# Use Aurelio with GitHub Copilot

**Aurelio's optional chat and analysis use the GitHub Copilot account authenticated on your
computer. Aurelio stores no model API key and adds no subscription of its own.** Everything
else in the app, including records, dashboards, portfolio calculations and goals, works
without Copilot.

## Connect Copilot

1. Install GitHub Copilot CLI.
2. Run `copilot login` and complete GitHub's authentication flow.
3. Run `copilot --banner` once. Accept GitHub's terms if the CLI asks.
4. Start or restart Aurelio.

Aurelio starts a short-lived Copilot SDK session for each model request. Authentication remains
owned by the Copilot CLI. Do not put GitHub tokens or model-provider API keys in `backend/.env`.

## Which model answers?

The default is `claude-opus-5.5`. The chat menu asks Copilot for every model available to the
signed-in account, including supported Claude and GPT models. Availability and quota depend on
the account's Copilot plan and may change in GitHub's service.

Optional settings in `backend/.env` choose defaults:

| Setting | What it chooses |
|---|---|
| `COPILOT_MODEL` | the default for everything |
| `COPILOT_CHAT_MODEL` | the chat when no model is picked in its menu |
| `COPILOT_ANALYST_MODEL` | the quantitative analyst |
| `COPILOT_CONFIDANT_MODEL` | the confidant who reads personal context |

Each role-specific setting falls back to `COPILOT_MODEL`, then to the built-in default. Giving
the two analysis roles different models can add different blind spots; one model in both seats
still works because the roles receive deliberately different context.

## What leaves the computer?

Records remain in Aurelio's local SQLite database. When you ask the chat or confirm an analysis,
the application sends the financial context needed for that request to GitHub Copilot and the
selected model provider. The analyst receives financial figures without personal questionnaire
answers; the confidant receives personal context without portfolio figures. The chat receives
the current financial picture needed to answer its question.

Web retrieval runs in a separate Copilot request. It carries the bounded search query, not the
conversation or financial records, and returns at most five pages to the requesting model.

## Usage and cost

Copilot reports token and subscription usage, not a per-request USD charge. Aurelio records input
and cached token counts when Copilot supplies them, but leaves its historical USD cost fields
empty for Copilot-backed calls. Plan limits, premium-request multipliers and billing belong to
the signed-in GitHub account; check GitHub Copilot's own usage page for the authoritative figures.

## Questions

**Do I need Copilot to use Aurelio?** No. Without an authenticated account, everything except the
chat and AI analysis remains available.

**Can I paste an Anthropic or OpenAI key into Aurelio instead?** No. This integration deliberately
uses the authenticated GitHub Copilot SDK boundary rather than accepting provider API keys.

## Next

- [GitHub Copilot usage in Aurelio](github-copilot-usage.md)
- [Ask AI whether a stock is worth buying](ask-ai-whether-a-stock-is-worth-buying.md)
