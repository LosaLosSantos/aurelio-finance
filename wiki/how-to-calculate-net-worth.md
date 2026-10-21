---
title: "How to calculate net worth"
description: "Net worth = assets minus liabilities: cash, investments and your home at today's value, minus your mortgage and other debts. The formula, a worked example with a mortgage, and how Aurelio builds each figure from dated records."
parent: "Net worth and cash"
nav_order: 1
---

# How to calculate net worth

**To calculate your net worth, add up what you own at today's value (cash, investments, your
home and anything else you could sell) and subtract what you owe (a mortgage, loans, card
balances): net worth = assets − liabilities.** For the demo household that ships with
Aurelio, €340,320 of assets minus a €199,500 mortgage is a net worth of €140,820. Aurelio
does the sum for you, and builds each part of it from dated records instead of a running
balance you have to trust.

## The formula, worked out

| | Demo household |
|---|---|
| Cash, on two accounts | €14,374 |
| Investments: two equity ETFs, a bond ETF, SAP shares | €20,946 |
| A flat, at its latest valuation | €305,000 |
| **Assets** | **€340,320** |
| The mortgage, at its latest balance | −€199,500 |
| **Net worth** | **€140,820** |

These are the figures of a demo built on 12 October 2026, with the investments at the prices
recorded in its last situation. Once the app is online it prices them from the market every
day, so the figure on your screen moves with the market.

## How do you calculate net worth with a mortgage?

Count the home at what it would sell for today, as an asset, and the mortgage at what you
still owe, as a liability. The difference is your equity in the home: in the demo, €305,000 −
€199,500 = €105,500, which Aurelio shows on the flat's page as "your equity €105,500". On the
Dashboard the two stay apart, the flat under real assets and the mortgage under debts.

Paying the mortgage does not lower your net worth by the whole installment. The part that
repays principal moves money from your cash into your equity; only the interest is gone.
Aurelio counts a loan at its last recorded balance, so record the balance from your statement
now and then: until you do, the installments leave your cash while the debt stays where it
was, and the net worth reads lower than it is by the principal repaid since.

## What counts as an asset, and what as a debt?

| Assets | Liabilities |
|---|---|
| cash in every account, at today's balance | a mortgage |
| investments at market value, not at what you paid | personal, car and student loans |
| a home, a car, a collectible, jewelry or art, at what it would sell for | credit card balances |
| a pension pot or other savings you can put a value on | anything else you owe |

In Aurelio, assets are recorded under Records as accounts (Wealth) and real assets, and
liabilities under Debts, each debt with its kind: mortgage, personal loan, auto loan, student
loan, credit card or other.

## How does Aurelio build each figure?

The Dashboard shows the net worth and the four figures it is made of. Investments and cash
together are your financial wealth; net worth is financial wealth plus real assets, minus
debts.

| Part | Where it comes from | When it moves |
|---|---|---|
| Investments | each account's latest situation (a dated list of what it held), plus the buys and sales recorded after it | every day, for positions with a ticker and a quantity, which are priced from the market; a position recorded as a value only stays at that value until you record it again |
| Cash | each account's latest recorded balance, plus the income, expenses, transfers and investment entries dated after it | on the date of each of those events |
| Real assets | the latest valuation of each home, vehicle or collectible | when you record a new valuation |
| Debts | the latest balance of each loan or mortgage | when you record a new balance |

Aurelio never keeps a running balance. Each account has situations, which are dated
photographs of what was there, and its value today is the latest photograph plus every entry
dated strictly after it:

```
   the latest dated record (a situation, a cash balance)
                         +
   everything dated after it (buys, sales, dividends, income, expenses, transfers)
                         =
                       today
```

A newer photograph starts the count again, which is what keeps anything from being counted
twice: what happened before it is already inside it. The "strictly after" is the whole rule.
A salary paid on the day of a recorded balance is already in that balance, and counting it
again would add it twice. What this buys you: a wrong number can be traced to a wrong record
or to a wrong event, and to nothing else.

The demo's bank account shows the rule at work: €10,400 recorded on 14 July, then three
salaries, three months of expenses and a transfer, make €13,240 on 12 October.
[Personal finance without bank sync](personal-finance-without-bank-sync.md) works it through.

## Priced and unpriced positions

A position recorded with a ticker and a quantity revalues itself: the quantity is from your
last situation, the price is today's. A position recorded as a value only, with no ticker,
stays at the figure you typed until you record it again. The two age differently, and the
Dashboard says how much of your investments is the second kind ("carried over from the last
situation, not priced"). The demo holds one of each on purpose: its euro government bond ETF
is recorded as a total, beside three positions the market prices every day.

## One currency

Every amount is converted into one base currency before it is added to anything: the euro
unless you choose another in Profile. The rates are the European Central Bank's
[daily reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html),
and each reading uses the rates of its own day: today's totals at today's rates, each point of
the net worth history at the rates of that point's day. For a position with a quantity, the
currency that counts is the one its listing trades in, not the currency of the fund's share
class: a class denominated in dollars can trade in euros on another exchange.

## Net worth over time

The Dashboard's chart reads the same rules at every date on which something happened: the
situation in force that day plus the entries after it for investments, the projected cash,
and the latest valuation and debt balance on or before that day. Tap or point at the chart,
or tab to it and use the arrow keys, for the financial, real and debt figures behind each
point; its table lists them all. Over a year or more, each date on its axis says its year.

## What Aurelio does not do

- **It does not read your bank or broker.** A balance, a situation or a valuation you have
  not recorded does not exist for Aurelio.
- **It does not amortize your debts.** A loan moves only when you record its next balance.
- **It keeps taxes beside the totals, never inside them.** A tax estimate, from the rates you
  declare in Profile, is shown next to realized gains and dividends and never enters the net
  worth, a cost or a position's value.

## Questions

**Is my home part of my net worth?** Yes, at what it would sell for today, with its mortgage
counted as a debt. Your equity in it is the first minus the second.

**Should I include a pension?** If you can put a value on it, many people do, as the pot's
current value. In Aurelio, record it as an account holding that value.

**How is net worth calculated for a couple?** The same way, on both people's assets and debts
together. Aurelio is built for one person or one household, so a couple can keep one set of
records for both.

**Why use market value and not what I paid?** Because net worth asks what you would have if
you sold today. What you paid matters for gains and taxes, which Aurelio shows on the
Portfolio page.

## Sources

- The summary the Dashboard shows: `compute_summary` in
  [analytics.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/analytics.py).
- The demo household: [demo.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/demo.py).
- The rules behind these numbers: [How Aurelio reasons](https://github.com/LosaLosSantos/aurelio-finance/blob/main/docs/how-aurelio-reasons.md).
