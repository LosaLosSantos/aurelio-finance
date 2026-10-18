---
title: "Personal finance without bank sync: track cash from one balance"
description: "A personal finance app without linking your bank account: record what an account held on one day and the income and expenses that move it, and Aurelio projects today's balance by itself."
parent: "Net worth and cash"
nav_order: 2
---

# Personal finance without bank sync: track cash from one balance

**You can track your money without linking a bank account: record what each account held on
one day, plus the recurring income and expenses that move it, and Aurelio, an open-source
personal finance app, works out today's balance by itself.** When your next statement arrives,
you record its balance and the projection starts again from there. No bank login, no import,
no categorizing of every card payment.

## What do you record?

- **A balance.** Under Records, Wealth, each account has its cash: "Actual cash" on a date,
  copied from a statement or a banking app.
- **Income and expenses.** Under Records, Cash flow: the amount, how often it comes round
  (monthly, quarterly, every six months, yearly, or once), the day it starts, the day it
  ends if it does, and the account it is paid into or out of. Each expense is essential or
  discretionary, which matters for the
  [emergency fund](how-many-months-of-emergency-fund-do-you-need.md).
- **Transfers** between your own accounts.
- **Investment entries.** A buy takes its cost out of the account that pays for it; a sale
  or a dividend brings money back.

## How is today's balance worked out?

```
today = the last balance
      + income − expenses
      + transfers in − transfers out
      − buys + sales and dividends
```

counting only what is dated strictly after the balance's day, up to today. The balance
already contains everything up to its own day, so a salary paid that same day is not added a
second time.

On the demo household, built on 12 October 2026, the bank held €10,400 on 14 July:

| Event | Amount |
|---|---|
| Balance recorded on 14 July | €10,400 |
| Three salaries, on 27 July, August and September | +€10,200 |
| Three months of expenses, on 1 August, September and October | −€6,360 |
| A transfer to the broker, on 13 August | −€1,000 |
| **Cash on 12 October** | **€13,240** |

The broker's account, €900 on the same day, received that €1,000 and paid €766 for four SAP
shares (€764 and €2 of fees), so it held €1,134.

## Dates, not averages

Two pages read the same records in two different ways, each right for its job:

- **Cash flow** speaks in monthly rates, for budgeting: the €540 yearly home insurance counts
  as €45 a month, a quarterly bill as a third of itself. That is where the savings rate comes
  from: €1,235 of the demo's €3,400 a month, 36%.
- **The cash projection** pays each item on its own day: the insurance leaves the account
  once a year, on its date, which is why it is not in the table above (it was last paid on
  1 November 2025).

A few rules follow from dates being dates:

- A payment set on the 30th or 31st falls on the last day of a shorter month and goes back to
  its own day the month after.
- An item paid once happens on its start date and never again.
- An item with no start date counts in the monthly rates but cannot move a balance: it has no
  day to happen on.

## How do you correct it?

Record the balance from your next statement on its day. From then on the projection starts
from it, and nothing dated before it is counted again.

The difference between what Aurelio projected and what the statement says is worth a look.
If the projection read €13,240 and the statement says €13,050, there are €190 of spending you
have not recorded, or something recorded that did not happen. Small gaps are normal: card
payments you never typed in. A gap that grows month after month is a recurring expense
missing from Cash flow.

You can also tell the chat, for example "my bank account had 13,050 today": it proposes the
new balance as a card, and writes nothing until you confirm it.

## More than one currency

Each balance, income, expense and transfer is recorded in its own currency, and one account
can hold rows in several. For the conversion sources and what a missing-rate warning means,
see [One currency](how-to-calculate-net-worth.md#one-currency).

## What it does not do

- It does not read your bank. What you have not recorded has not happened, as far as the
  projection knows, until the next balance includes it.
- It does not guess. An account with no balance on record has no starting point, so its cash
  counts as zero until you record one; when the chat works out what you could invest, it
  names those accounts.

## Questions

**Why track money without bank sync?** Bank sync works through a connection to your bank,
usually held by a third-party aggregator. Recording a balance by hand needs no connection at
all, and it is still enough for a balance, a savings rate and a net worth, because the
recurring items do most of the work.

**How often should I record a balance?** Whenever a statement arrives is plenty; once a month
keeps the projection close for most accounts.

**What if I forget an expense?** The next balance you record absorbs it: from that day the
projection starts from what the account really held.

## Sources

- The projection: `compute_cash_position` in
  [analytics.py](https://github.com/LosaLosSantos/aurelio-finance/blob/main/backend/app/analytics.py).
- [How to calculate net worth](how-to-calculate-net-worth.md): the same rule, applied to
  investments, real assets and debts.
