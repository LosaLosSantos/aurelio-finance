---
title: "Accumulating vs distributing ETFs: which is better?"
description: "An accumulating ETF reinvests its dividends inside the fund, a distributing one pays them to you in cash. Which is better depends on whether you need the income and on your country's taxes. What each changes for your cash and your records, and how Aurelio records them."
parent: "ETFs and funds"
nav_order: 2
---

# Accumulating vs distributing ETFs: which is better?

**An accumulating ETF reinvests the dividends it receives inside the fund, so its price grows
by that much; a distributing ETF pays them out to you in cash, usually a few times a year.
Neither is better in general: distributing suits you if you need the income, accumulating if
you would reinvest it anyway, and your country's taxes can decide it.** The two versions
often track the same index with the same holdings and carry the same name, with "(Acc)" or
"(Dist)" at the end: the difference that matters is what happens to the dividends.

## What actually differs?

| | Accumulating | Distributing |
|---|---|---|
| Dividends | reinvested inside the fund | paid into your account |
| Your cash | does not move | grows on each payment |
| The price of a share | includes the reinvested dividends | falls by about the dividend on the ex-date |
| Reinvesting | automatic, inside the fund | up to you, with your broker's fees |
| Suits | building wealth you do not need to spend yet | living on the income, or wanting cash without selling |

## Which is better?

A few questions decide it for most people:

- **Do you need the income now?** If you would spend the dividends, distributing pays them
  without you selling anything. If you would reinvest them, accumulating does it for you.
- **How does your country tax each kind?** In many countries a distribution is taxed in the
  year it is paid, while an accumulating fund's reinvested income is taxed only when you sell;
  some countries tax an accumulating fund's income every year anyway. Check your own
  country's rules before choosing on tax grounds.
- **Would reinvesting each payment cost you?** With a distributing fund, every reinvestment
  is a purchase, with its fees and your attention.

## The twins, always shown together

Most large ETFs come in both versions. In Aurelio's fund picker the accumulating and the
distributing twin are always listed side by side: they carry the same name and differ in what
they do with dividends, and showing one alone invites picking it without knowing there was a
choice.

## How Aurelio records dividends

Each holding has a dividend policy, under Records, Wealth:

- **Distributing**: the app follows the fund's dividends.
- **Accumulating**: no dividend is recorded, because the fund reinvests them.
- **From its history**: the holding's own dividend history decides. It is what a holding with
  no policy follows, and the right one for a share, which has no policy to choose: it pays or
  it does not.

For a holding it follows, the app reads the dividend history from Yahoo Finance when it
starts (at most once a day per ticker) and, for each ex-date, credits the account's cash with
the dividend per share times the shares you held before that date. The number of shares is
reconstructed from the situation in force at the ex-date and your ledger, so a dividend is
recorded even if you open the app months later.

The money reaches your account on the payment date, days or weeks after the ex-date, and the
row is dated on that day where Yahoo says it: for shares listed in the US, whose payment
dates Yahoo gives for the latest or the next dividend (14 to 69 days after the ex-date, in
the twelve measured in October 2026). For shares listed elsewhere and for funds Yahoo gives
no usable one, so the row is dated on its ex-date, and correcting it with your broker's statement
moves it to the day the money arrived. Either way the dividend keeps its ex-date, which is
how the app knows it is recorded: never twice.

A dividend you entered yourself is recognized as the one the app was about to record when it
is dated in that dividend's window, from its ex-date to the next one or 70 days after it,
whichever is later, and no other entry or dividend could pair with it. When the app is not
sure, it asks you instead of guessing. It also asks when your latest cash balance falls
between an ex-date and a payment date it does not know: whether the money was already in
that balance.

To do that it needs a ticker and a quantity. The demo's euro government bond ETF is a
distributing fund recorded as a total, with no ticker, so its dividends cannot be followed:
nothing says how many shares it held on each ex-date.

## Gross, estimated, and then yours

A dividend the app records by itself is born gross and marked **estimated**: the market knows
nothing of the tax withheld before the money reached you. When you correct it with what your
broker actually credited, the net amount replaces the gross one and the estimated mark goes in
the same step.

For the dividends still at the market's gross figure, Profile has a **dividend withholding
rate** you declare. The estimate it produces is shown beside your totals and never inside
them, with the rate in plain sight, and it applies only to dividends still marked estimated:
one you corrected by hand is not taxed a second time. Profile can propose your country's
rates as a starting point, but never applies them on its own.

A dividend paid in another currency is converted at the rate of its own ex-date, not today's.

## Questions

**Do accumulating ETFs pay dividends?** Not to you. The fund receives the dividends of the
companies it holds and reinvests them, so you see them in the fund's price instead of in your
account.

**Can I switch from one version to the other?** Only by selling one and buying the other,
which is a sale like any other: it may be taxed, and it costs the fees of two trades.

**Do the two versions hold different companies?** No. Their look-through is the same; see
[ETF overlap and portfolio X-ray](etf-overlap-and-portfolio-x-ray.md).

## Sources

- How dividends are followed and recorded: [pac.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/pac.py).
- How an entry you typed is paired with the dividend it pays: [dividend_pairs.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/dividend_pairs.py).
- [How to calculate net worth](how-to-calculate-net-worth.md): where the dividend cash ends up.

*Educational information, not regulated financial advice.*
