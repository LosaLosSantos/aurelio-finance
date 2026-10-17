---
title: "Ask AI whether a stock is worth buying"
description: "A useful answer to 'should I buy this stock?' is about you as much as the stock. Why a general chatbot falls short, and how Aurelio's chat answers from your own records: what the instrument is, how it fits, a verdict with its reasons, and an amount the records allow."
parent: "AI and money"
nav_order: 1
---

# Ask AI whether a stock is worth buying

**An AI asked whether a stock is worth buying can explain the stock; a useful answer is also
about you: what you already hold, what you can afford to put in, and what the model does not
know.** Aurelio, an open-source personal finance app, answers the question in its chat as one
evaluation, in a fixed order, from your own records, and the amount in it is computed by the
app, not by the model's arithmetic.

## Should you ask ChatGPT for financial advice?

A general chatbot, ChatGPT, Claude or Gemini in a browser tab, can explain what a fund or a
company is. Four things limit what it can say about you:

- **It does not know what you hold**, unless you paste it in every time. You may already own
  the company through a world fund, or have half your investments in the same sector.
- **It does not know what you can afford.** Your cash, the reserve you keep, the plans and
  goals your money is already promised to.
- **It does arithmetic in prose.** Measured while building this feature, on a test database:
  asked twice on the same records, Claude Opus 5.5 gave a goal's monthly need as 631 in one
  answer and 650 in the next. A figure about your money should not depend on which answer you
  got.
- **It may answer from memory.** A fund's costs and a company's results change; what a model
  remembers from its training may not.

## How does Aurelio answer?

Asked "is this worth buying for me, and how much?", the chat answers in this order:

1. **What it is, read and never recalled.** For a fund, what Aurelio's fund catalogue says of
   it: where it is domiciled, what it costs, what it does with dividends, how it holds what it
   tracks. For a share, its listing and the currency it is quoted in. When it helps, a web
   search for what the company is doing (results, valuation, risks, news), with the links.
2. **How it fits you.** What a sum would weigh in your investments, and in each region,
   sector, company and currency, read through your funds'
   [X-ray](etf-overlap-and-portfolio-x-ray.md), and how much of it you already hold through
   the funds you have.
3. **A verdict that says what it rests on**: your records, those figures, and what it does
   not know.
4. **How much**, within the figures the app computes, with what it assumed.
5. **A card** carrying that amount, or, when the verdict is no, the reason and no card.

## What does an amount stand on?

These figures are worked out by the app from your records, the same way every time, and each
says where it comes from. On the
[demo household](self-hosted-personal-finance-app.md#try-it-on-the-demo-first) on 12 October
2026:

| Figure | Demo | Where it comes from |
|---|---|---|
| Cash on the accounts | €14,374 | each account's projected cash |
| Reserve | €11,430 | six months, the app's default and said as such, times €1,905 of essential expenses |
| **Cash above the reserve** | **€2,944** | the most a sum put in now may be |
| Left each month | €1,235 | €3,400 of income less €2,165 of expenses |
| Already committed each month | €250 | the car goal's recorded contribution |
| **Left after commitments** | **€985** | the most a monthly sum may be |
| Not counted yet | €300 | the world fund plan, which starts next month |
| Left if each goal got its need | €846.20 | the car lacks €138.80 a month of the €388.80 it needs with no growth |

The reserve is [your own number of months](how-many-months-of-emergency-fund-do-you-need.md)
when you have answered the question in Profile. A plan that starts later is listed, not
subtracted. What each goal would need is said beside the figures and never taken out of them:
what is committed is what you recorded, and whether a goal deserves more is yours to weigh.

## The card

A purchase idea reaches you as a card. The chat is told to name a security only that way:
never as a buy or sell call in prose, and never unasked. Each card carries three things, all
required:

- **why this one**;
- **what you declared that it rests on**: a position, a profile answer, a goal, something you
  just said;
- **what it does not know** that would change it. A month later, this is usually the line
  that decides.

When you asked how much, the card carries the amount, with what the chat assumed in choosing
it and the figures it stood on that day. An amount above what the records allow (a sum now
above €2,944, a monthly sum above €985, in the demo) is refused, with those figures. Every
suggestion card says: "This is educational information, not personalised regulated advice."

The instrument is checked before the card exists. A fund is named by an ISIN from the fund
catalogue, a share by a symbol Yahoo lists as a share, and the card reads the name and the
facts from there, not from the model. No card is drawn for a coin, a single bond, or a fund
the catalogue does not hold. A commodity is named only through a product that physically
holds it: a future, or a product that follows futures through a swap, holds none of it. When
no product in the catalogue holds it, as for oil, the chat says so and why, and draws no card.

At most three cards come in one answer, and only when you asked for several.

## Accepting a card buys nothing

Accepting a card puts the idea on your watchlist, on the Portfolio page, with its amount, what
it assumed and what it stood on. No broker is connected: nothing is bought, no position
appears, and no total moves.

## What did it do when measured?

Four scouting questions on a test database in October 2026 (a share, a UCITS ETF, gold and
oil), on Claude Opus 5.5: every amount came from the app's figures, the reserve was said as
the app's six-month default each time, and the goal's monthly need was 631.08 in all four
answers, where the model's own arithmetic had given 631 and 650. Three cards carried an amount
within what the records allowed, and oil drew none, every oil product in the catalogue being
swap based. The web was searched for the share and for gold, every claim with its link.

This path uses multiple Copilot requests when it needs tools or web retrieval. See
[GitHub Copilot usage in Aurelio](github-copilot-usage.md).

## Questions

**Can AI tell me which stock to buy?** It can explain an instrument and weigh it against your
records. In Aurelio it names one only on a card, with why, what it rests on and what it does
not know, and only when you ask; the decision, and the purchase, stay yours.

**Does Aurelio buy anything?** No. No broker is connected; an accepted card is an idea on the
watchlist.

**Is it financial advice?** No. It is educational information, not regulated financial
advice, and every suggestion card says so.

## Sources

- What an amount stands on: [sizing.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/sizing.py).
- What a purchase would weigh: `weigh_purchase` in
  [composition.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/composition.py).
- [AI portfolio review](ai-portfolio-review.md): when the chat has advice to give, it builds
  on the latest analysis.

*Educational information, not regulated financial advice.*
