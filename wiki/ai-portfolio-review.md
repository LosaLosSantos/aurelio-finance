---
title: "AI portfolio review: an analysis that argues with itself"
description: "One AI model asked once tends to agree with itself, and with you. Aurelio's AI portfolio review splits the work between an analyst who sees only the numbers and a confidant who knows you but never sees them, and keeps their disagreement in the answer."
parent: "AI and money"
nav_order: 2
---

# AI portfolio review: an analysis that argues with itself

**A single AI model asked to review your portfolio tends to agree with itself, and with you.
Aurelio's AI portfolio review gets a second opinion out of what each role is allowed to see:
an analyst judges the numbers without knowing whose they are, a confidant who knows the
person challenges the findings without seeing the numbers, and the final answer keeps any
disagreement instead of averaging it away.** The review runs on your own records, inside
Aurelio, an open-source personal finance app.

## Why is one model not enough?

A model that sees your figures and your hopes at the same time can bend one to fit the other:
a portfolio full of risk reads as "bold" next to a profile that says you like risk. More models
do not fix that if they all see the same thing. Different information does. So the roles are
built on what they are not shown.

## The four steps

| Step | Sees | Does not see | Its job |
|---|---|---|---|
| **Analyst** | the investments and everything else you own and owe: cash, the income and expenses in force, real assets, debts, and the country you pay tax in with the rates you declared | who you are: no profile answers, no goals | judge the portfolio on the numbers alone, checking what it can |
| **Confidant** | you (profile and goals) and the analyst's findings | the figures of your records | argue about fit, temperament and framing, and say whether it is challenging something that matters |
| **Revision** (only when the challenge is contested) | the figures again, its own analysis and the challenge | who you are, beyond what the challenge says | answer it point by point, marking each point REVISE or HOLD; silently dropping one is not allowed |
| **Synthesis** | the analysis, the challenge, the revision if there was one, and how you describe yourself | the raw figures, beyond what the analysis quotes | write the one answer you read, leading with what to do and why, with any remaining disagreement left in |

The analyst and its revision can look things up before they answer: the look-through of your
funds, what the fund catalogue holds on a fund's index and at which costs, what an instrument
is and its latest close, what a purchase or a sale would change, and, on Claude and GPT models,
the web. None of these reads your profile answers or your goals, and a test in the code plants
markers there to check that none of them reaches the analyst.

The prompts ask for friction on purpose: two polite models converge into agreement that
carries no information.

## How deep does it go?

The analyst, the confidant and the synthesis always run. The revision runs only when the
confidant actually disagrees, which its own instructions make it say. When the disagreement is
real, the loop goes round again: the confidant reads the revision and says whether its
challenge still stands, and the analyst answers once more. A run is three steps when there is
nothing to argue about and up to six when there is. A step of the analyst's is one request to
the model, or up to four, with up to three web searches, when it looks things up.

Tool rounds and web retrieval consume additional subscription quota; see
[GitHub Copilot usage in Aurelio](github-copilot-usage.md) for usage accounting.

## How do you run one?

You ask the chat for an analysis. It answers with a card describing the steps and lookup bounds,
quoting the last run's measured duration when available, and nothing starts until you confirm it.
You can then watch each step arrive, and read the result in the main column, where each step is
labelled: "Analyst · sees only the numbers", "Knows you · has not seen the numbers", "Analyst ·
answers the challenge", and "The answer". Past analyses are listed from the chat's history.

The chat also proposes one by itself when the last analysis is older than what it can see,
for instance "the last one is from 12 August and two positions have been added since: run a
fresh one?". When you ask for advice and the last analysis is current, the chat reads it and
builds on it.

## The chat cannot steer it

What the roles read is built from your records, never from your conversation with the chat.
The chat can propose a run but cannot tell the analyst what to find: an analysis that the
conversation could steer would only repeat the conversation.

## Different models for different roles

Each role can run on its own model. Different models bring different blind spots, which is what a
panel is for. One model in both seats still works, because what separates the roles is what
each one is shown, not the model behind it. See
[Use Aurelio with GitHub Copilot](github-copilot-models.md).

## Questions

**Can AI review my investment portfolio?** It can read the positions, the allocation and the
rest of your finances and say what stands out. What it cannot do on its own is disagree with
itself, which is why Aurelio splits the review between roles that see different things.

**Which AI model is best for a portfolio review?** Any suitable model offered to the signed-in
Copilot account can run it; see the [model guide](github-copilot-models.md) for defaults. Putting
a different model in each role adds different blind spots, which is the point of a panel.

**Does the review change my records?** No. It writes a document you read; your records change
only through cards you confirm.

## What it is not

It is not a forecast and not a trading signal. Like everything the chat says, it is
educational information, not regulated financial advice.

## Sources

- The roles, their prompts and the variable depth: [chain.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/chain.py).
- What the analyst can look up: [analyst_tools.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/analyst_tools.py).
- [Ask AI whether a stock is worth buying](ask-ai-whether-a-stock-is-worth-buying.md)
- [GitHub Copilot usage in Aurelio](github-copilot-usage.md)
