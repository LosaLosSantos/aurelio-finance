---
title: "ETF overlap and portfolio X-ray: what your funds really hold"
description: "ETF overlap is the money you hold in the same companies through more than one fund. How Aurelio's portfolio X-ray opens every fund you hold, from the issuers' own files where they publish them, and adds up the companies, countries, sectors and currencies inside."
parent: "ETFs and funds"
nav_order: 1
---

# ETF overlap and portfolio X-ray: what your funds really hold

**ETF overlap is the part of your money that sits in the same companies through more than one
fund. A portfolio X-ray, also called a look-through, finds it by opening every fund you hold
and adding up what is inside, weighted by what each fund is worth to you.** Funds with
different names often hold the same large companies, so a portfolio of three "global" funds
can be a bigger bet on a few of them than any single fund's factsheet shows. Aurelio, an
open-source personal finance app, runs this X-ray on your own portfolio, for free.

## How do you check ETF overlap?

Comparing two funds' top ten holdings is the quick way, and it undercounts: a company ranked
11th in one fund and 3rd in another never shows up. The complete way needs three things:

1. every position of every fund, not just its top ten;
2. each fund weighted by what you actually hold of it today;
3. the same company recognized under the slightly different names two files give it.

Aurelio does all three for the funds it can read from the issuer's own file (iShares and
Vanguard funds), and says so when a fund is known only by its top ten.

## Where do the holdings come from?

A fund's composition is fetched from the best source that answers, in this order:

1. **The issuer's own file**, where Aurelio knows how to read it. iShares publishes every
   position of a fund, refreshed daily, with a country and a sector on each line. Vanguard
   publishes every position at month end, so about three weeks behind. Which file is a
   Vanguard fund's is read from Vanguard's own list of its funds (414 on October 21, 2026),
   asked only when you hold a Vanguard fund it has not found yet, at most once a day unless
   Vanguard did not answer, and kept. Each line of Vanguard's file says what it is, so only
   its shares count as companies. A fund of funds, such as Vanguard LifeStrategy, is read
   from justETF instead: its own file lists the funds it holds, not what they hold.
2. **justETF**, for the UCITS funds the issuers' files do not cover: countries, sectors and the
   ten largest holdings.
3. **Trackinsight**, by ticker, when no ISIN is known.
4. **Yahoo Finance**, as a last resort: sectors and the ten largest holdings.

Why the issuer first: a published top ten is shallow, and sometimes wrong. A case recorded
in Aurelio's code: when it was checked, justETF's top ten for iShares Edge MSCI World Min
Volatility listed NVIDIA, while iShares' own file ranked it 12th and put Microsoft 7th. Anything built on a top
ten, the overlap between funds above all, inherits that kind of error.

The ISIN is what unlocks the best source. A ticker prices a position on one exchange; an ISIN
identifies the fund itself, wherever it trades. A fund the X-ray cannot open usually just
needs its ISIN: add it to the holding under Records, Wealth.

Compositions are kept for 15 days, and "Update composition" on the Portfolio page fetches them
again. A refresh never makes an entry worse: if the issuer's file fails and only a top ten
answers, the complete composition already stored is kept.

## What does the X-ray add up?

Each fund's percentages are weighted by what the fund is worth today, as a share of all your
investments. Today's value, not what you paid: a fund that tripled carries three times the
exposure it was bought with.

The Portfolio page then shows, under "Look-through (real exposure)":

- **Countries**, **Sectors** and **Currency exposure**, each as a percentage of the portfolio;
- **Companies**: the companies whose shares you hold, through every fund and directly, as a
  percentage of the portfolio;
- a grid of asset class by region;
- **Overlap**: the same company's shares inside two or more of your positions, and through
  which ones.

A share you hold directly counts as one holding of itself, with its own country and sector.
In the demo, the SAP shares held directly and the SAP inside the MSCI World fund meet on one
line under Companies: names are matched without their legal form, so "SAP SE" and "SAP" are one
company, and so are "NVIDIA CORP" and "NVIDIA Corp" from two different issuers' files.

A bond fund's file lists its issuers' bonds under the issuers' names, so by name alone a
company's bonds in a bond fund and its shares in an equity fund would read as one stock held
twice. Where a fund's file says what each line is, only its shares count under Companies and
Overlap; its bonds, cash and futures still count in the countries and sectors. Where nothing
says what a line is (a published top ten, for instance), the class you recorded the position
under decides: a fund recorded as Bonds names no company, and any other counts its lines as
shares. A bond fund recorded under Stocks & ETF can therefore still put a government among the
companies when its source does not say what its lines are.

## What can it not see?

- **Coins, and positions recorded without a ticker or an ISIN.** There is nothing to open,
  so they stay whole, and the page says what share of the portfolio it actually covers.
- **The full overlap, when a fund is known only by its top ten.** The page says when that is
  the case: complete for funds read from the issuer's file, a floor for the others.
- **Where companies earn their money.** Currency exposure follows the country each company
  belongs to, not where its revenue comes from, and it ignores currency hedging: a euro-hedged
  share class still shows the currencies of what the fund holds.

## Before you buy

The same X-ray answers a question before you buy. Asked whether a fund or a share is worth
buying, Aurelio's chat folds the purchase in as if you already held it, and reads what
changes: the sum's weight in your investments, the five countries, sectors, currencies and
companies that move most, and what the new fund holds that you already own through the funds
you have. See [Ask AI whether a stock is worth buying](ask-ai-whether-a-stock-is-worth-buying.md).

## Questions

**Is there a free ETF overlap tool?** Aurelio's look-through is free and open source, and runs
on your own computer against your own holdings, weighted by what you hold of each fund.

**Why does overlap matter?** Because diversification is about what you own, not how many funds
you own. Two world funds can put the same large companies in your portfolio twice, and the
X-ray shows how much of your money ends up in each one.

**Do accumulating and distributing versions of a fund overlap?** Completely: they hold the
same companies and differ only in what they do with dividends. See
[Accumulating vs distributing ETFs](accumulating-vs-distributing-etf.md).

## Sources

- The X-ray and its sources: [composition.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/composition.py)
  and the issuers' files, [issuers.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/issuers.py).
- [How to calculate net worth](how-to-calculate-net-worth.md): where the investments' value
  comes from.

*Educational information, not regulated financial advice.*
