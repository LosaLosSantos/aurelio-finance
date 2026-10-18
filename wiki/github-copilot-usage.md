---
title: "GitHub Copilot usage in Aurelio"
description: "How Aurelio uses GitHub Copilot quota, what token figures it records, and why it does not show a dollar cost per question."
parent: "Guides"
nav_order: 3
---

# GitHub Copilot usage in Aurelio

**Aurelio uses the subscription and quota attached to the GitHub Copilot account signed in on
your computer. It does not buy model tokens, accept a model-provider API key, or calculate a
USD price per question.** Aurelio itself remains free and open source.

## What Aurelio records

When the Copilot SDK reports usage, Aurelio stores the input-token count and how many input
tokens came from cache. A tool-using turn can contain several model rounds, so those figures are
summed across distinct calls within each round and across the turn. Reported counts remain
recorded when a chat turn subsequently fails. These stored token counts cover the answering
rounds, not the separate web-retrieval requests. Missing usage remains empty rather than
becoming an invented zero.

The database retains nullable historical USD cost columns for existing installations, but every
Copilot-backed call leaves them empty. Copilot subscription quota, premium-request multipliers
and account billing are not equivalent to a per-call USD price.

## What consumes usage

- **A chat round.** Each question sends the current financial picture and conversation needed to
  answer it.
- **Tool follow-ups.** If the model asks Aurelio to read fund look-through, size a purchase or run
  another app tool, it receives that result in another model round.
- **Web retrieval.** Each bounded search is a separate Copilot request carrying only its query.
- **An analysis.** The analyst, confidant, revisions and synthesis are separate requests. An
  analysis has three to six steps, and analyst steps may use additional tool rounds.

A larger record, a longer conversation, more tool rounds and a deeper analysis can therefore use
more quota. Caching can reduce repeated input work, but the account's own Copilot usage page is
the authoritative record.

## Choose the models

The chat menu lists every model available to the authenticated account. Optional settings can
choose separate defaults for the chat, analyst and confidant. See
[Use Aurelio with GitHub Copilot](github-copilot-models.md).

## Questions

**Does Aurelio add a subscription?** No. GitHub Copilot access belongs to the signed-in GitHub
account; Aurelio adds no paid service.

**Why is the old cost field empty?** It represented provider-reported USD charges. Copilot reports
subscription usage instead, and relabeling quota as dollars would be false.

**Where do I check limits or billing?** In GitHub Copilot's own account and usage pages. Those
figures depend on the account's current plan and are not inferred by Aurelio.
