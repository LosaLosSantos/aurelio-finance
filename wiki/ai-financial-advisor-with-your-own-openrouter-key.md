---
title: "An AI financial advisor with your own OpenRouter key"
description: "Aurelio's AI financial advisor runs on any model OpenRouter serves, paid per question with your own API key. How to create the key, cap what it can spend, and choose which model answers."
parent: "Guides"
nav_order: 2
---

# An AI financial advisor with your own OpenRouter key

**Aurelio's AI financial advisor runs on any model that OpenRouter serves, paid with your own
API key: you put the key in `backend/.env`, and you pay OpenRouter per question, with no
subscription to Aurelio.** OpenRouter is a gateway that sells access to many companies' models
through one account. Everything else in the app (the records, the Dashboard, the Portfolio,
the look-through, the goals) works without a key; the key is needed only by the chat and the
analysis.

## How do you connect it?

1. Create an account at [openrouter.ai](https://openrouter.ai) and add credit.
2. Create a key at [openrouter.ai/keys](https://openrouter.ai/keys). OpenRouter lets you give
   a single key a credit limit: worth setting, see below.
3. In the `backend/` folder, copy `.env.example` to `.env` and put the key after
   `OPENROUTER_API_KEY=`.
4. Restart Aurelio. The key is read when the server starts.

`backend/.env` is ignored by git, so it never ends up in a commit. `.env.example` is tracked,
so never put a real key in it.

## Cap what the key can spend

OpenRouter's documentation describes a key's limit as "an optional spending cap configured on
an individual API key" ([API reference, limits](https://openrouter.ai/docs/api-reference/limits)).
It is the simplest protection there is: whatever happens, the key stops at that figure.

Leave it some room, though. Before each request OpenRouter holds the most that request could
cost: its input plus the longest answer the app allows, which is 8,192 tokens for a round of
the chat and 16,384 for a request of the analysis (about $0.16 and $0.33 of output on the default
model). A key with less than that left is refused, even when the real answer would have cost
two cents.

When that happens, the chat does not just fail: it says whether the key's limit, the
account's credit or the requests still running on the account stopped it, and where on
OpenRouter to change it.

## Which model answers?

The default is `anthropic/claude-opus-5.5`, at $4 per million input tokens and $20 per million
output tokens (prices checked in October 2026). It is a large model on purpose: a wrong
number about your money costs more than a slow answer.

The model menu in the chat offers these:

| Model | Context | Price per million tokens, in / out |
|---|---|---|
| `anthropic/claude-opus-5.5` | 1M | $4 / $20 |
| `anthropic/claude-sonnet-4.6` | 1M | $3 / $15 |
| `openai/gpt-6.1-sol-pro` | 1.05M | $2 / $10 |
| `qwen/qwen3.8-max-0902` | 1M | $2 / $6 |
| `moonshotai/kimi-k3` | 1M | $3 / $15 |
| `moonshotai/kimi-k2.6` | | about six times cheaper than K3 |

The prices are OpenRouter's as checked in October 2026 (August for the two Kimi models), and
they change: the [models page](https://openrouter.ai/models) has today's.

Any other model OpenRouter serves can be set by its slug in `backend/.env`, and it then
appears in the chat's menu too:

| Setting | What it chooses |
|---|---|
| `OPENROUTER_MODEL` | the default for everything |
| `OPENROUTER_CHAT_MODEL` | the chat's model when nothing is picked in its menu |
| `OPENROUTER_ANALYST_MODEL` | the analyst in the analysis |
| `OPENROUTER_CONFIDANT_MODEL` | the confidant in the analysis |

Each one left empty falls back to `OPENROUTER_MODEL`, and that to the default. Giving the two
roles of the analysis different models brings different blind spots, which is the point of
the [AI portfolio review](ai-portfolio-review.md); one model in both seats still works,
because what separates the roles is what each is shown.

## What happens when OpenRouter retires a model?

OpenRouter's public list of models gives some of them "the date after which the model may be
removed"
([API reference, models](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)):
17 of the 470 it listed on 17 October 2026, from 3 to 75 days ahead. Aurelio reads that list
once a day and says it before a call to such a model fails:

- The chat's menu shows the date beside the model's name ("may be retired after
  2026-10-31"; closed, "until Oct 31"), and marks a model the list no longer has ("no
  longer listed by OpenRouter"; closed, "not listed") without hiding it, since a model has
  been seen to leave the list and still answer.
- From 30 days before the date, a line above the chat's question box names the model the
  next question goes to, the date, and where it is set: a setting in `backend/.env`, the
  app's built-in default, or the menu. The analysis's card says the same of the models a run
  would call; both say it, too, of the model the web searches run on, when the model in use
  can search.

If OpenRouter then stops serving a model you set, the chat says so, names the setting that
chose it, and lists the dated versions OpenRouter still serves, if there are any.

Reading the list is one request a day to OpenRouter, with no key and nothing of yours in it:
it reaches OpenRouter from your computer's address, as every question to the chat does, and
nothing more is sent. With no key set it is never made, and on a day the list cannot be read
the app says nothing about dates.

## Can it search the web?

Yes, when a question needs it, for instance what a company has reported lately. One search
is a separate request to OpenRouter with your key, run by a small model (Claude Haiku 5.5),
and it carries the query and nothing else: no records, no conversation. Each costs $0.0073 to
$0.0075 on top of the round that asked for it.

## Questions

**Can I use OpenAI or Anthropic directly, without OpenRouter?** Not without changing the
code: Aurelio talks to OpenRouter's API, which routes each request to the company behind the
model you picked, OpenAI and Anthropic included.

**Do I need a key to use Aurelio?** No. Without one, everything but the chat and the analysis
works.

## Next

- [How much does an AI financial advisor cost?](how-much-does-an-ai-financial-advisor-cost.md):
  what real questions cost on the default model.
- [Ask AI whether a stock is worth buying](ask-ai-whether-a-stock-is-worth-buying.md): what
  the chat does with the key.
