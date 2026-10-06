# How Aurelio reasons

This page describes what the app is built on and the rules its code defends. It
is not a roadmap and not a status report: the code and its tests are the
status. Each rule below is here because its absence once produced a wrong
number.

## The north star

A complete and useful picture of one person's finances (wealth, cash flows,
goals and the context of their life), rich enough for a language model to
reason about. Everything stays local, for one user.

## The core idea: an anchor, plus the events after it

Wealth is not a running balance. Each institution has **situations**, dated
photographs of what was held there (`snapshots` in the database), and today's
state is the latest photograph plus every ledger entry dated **strictly after**
it.

```
            anchor (a dated situation)
                        +
   events dated after the anchor (ledger, transfers)
                        =
                      today
```

A newer photograph re-bases the calculation, and that is what prevents double
counting. The strictness of that "after" is not a detail: it is the central rule
of the model, and the code states it in one place, `backend/app/dated.py`.

What it buys: a wrong number can be traced either to a wrong photograph or to a
wrong event. There is no third possibility, and no balance you have to trust.

Cash works the same way. A **cash anchor** is an actual balance on a date, and
the app projects it forward with the income and expenses linked to that
institution, the transfers in and out, and what the investment ledger spent or
brought back.

## The domain map

```
WEALTH                    FLOWS                  PLANNING / CONTEXT
institutions              income_sources         goals
  ├ cash_anchors          expenses               survey_responses
  └ snapshots             transfers              accumulation_plans
      └ holdings                                   ├ plan_targets
                                                   └ plan_unfilled_occurrences
transactions (the ledger: buy · sell · dividend · close)

real_assets                     liabilities
  └ real_asset_valuations         └ liability_balances

                  ↓ everything flows into ↓
           DASHBOARD · PORTFOLIO (with the look-through)
                  ↓ which feeds ↓
           THE CHAT: reads everything, proposes, and runs the ANALYSIS
           (chain_runs · chain_steps: a blind analyst, a confidant, a revision
            only when the challenge is contested, a synthesis)
                  ↓ and what it suggests, if you keep it ↓
           watchlist_items: ideas, not holdings. No total counts them, and
           each carries why, what it rested on, and what it did not know.
```

Caches and supporting registers: `price_cache`, `fx_rates`, `composition_cache`,
`instruments` (the local UCITS fund catalogue, with a full-text index) and
`settings`. The chat keeps its conversations in `chat_conversations` and
`chat_messages`.

## The distinctions the code defends

These are the part of this page worth reading twice. Each exists because its
absence has already produced a wrong number.

**Tracked versus opaque.** A position with a ticker and a quantity revalues
itself; one recorded as a value only ages whole, and only you can update it. The
two age differently: on a priced row the value is today's and only the quantity
is old; on an opaque row everything is old.

**Identity versus quotation.** An ISIN identifies a fund; a ticker prices one of
its listings. The same fund has a different ticker on every exchange, so one
field cannot do both. Hence the two lanes of the instrument picker, which must
not be merged: the catalogue knows identities and no quotation, and the live
lookup knows a symbol that prices and no ISIN. Merged, the local lane, which is
instant, would wait for the network on every search, and an outage of the
lookup would empty a list that had good local results.

**Provenance travels with every number, and with every idea.** A cost is
recorded or estimated, and says which. A value carries the day it was
confirmed. A conversion carries the date of its rate. This is not pedantry: it
is what separates a measured gain from an invented one. A watchlist line is not
a number, but it follows the same rule: why this, based on what you declared,
and what the suggestion did not know. A month later, the last of the three is
the one that decides.

**Nothing leaves the totals without saying where it went.** Selling is a dated
statement with proceeds; disappearing from a photograph is not. Positions that
a newer photograph stopped naming are reported, never dropped in silence, and
beside them what the same photograph declared instead, because the two are
often the same money described better.

**A tax estimate sits beside the totals, never inside them.** The app takes a
rate you declare (yours, not a table) and applies it to two things the register
already has: realized gains and dividends. The figure never enters the net
worth, a cost basis or a position's value: it lives beside them, labelled
estimated, with the rate in plain sight. That keeps it an aid to deciding
rather than something pretending to be a tax return. The risk this rule avoids
is not approximation; it is being precise and wrong, which in tax matters is
worse. If a second rule is ever needed for a particular kind of instrument (a
rate for government bonds, a fund wrapper, a holding period), that is the line
beyond which this stops being a declared estimate and becomes a tax engine
without any of a tax engine's obligations.

**Estimated withholding applies only where `estimated` is true.** A dividend
the app records by itself is born gross, because the market knows nothing about
withholding. Correcting it with what your broker actually credited replaces the
gross amount with the net one **and clears `estimated` in the same gesture**,
and no gross or net column remains to recover the distinction from. Applying
withholding to everything would tax a second time exactly the rows someone
took the trouble to correct: the diligent reader punished for their diligence.

**An occurrence that came round is not an occurrence that bought.** For a
recurring investment plan, deducing the second from the first once made the
plan spend more than it had received.

**A day's close belongs to that day, or the app waits.** A sum fixed on a date
(a plan's purchase, the debit it causes, the rate that converts it) takes that
date's close. If the market has not published it, the previous day's is not
taken: that would be a purchase on a day it did not happen, inside a debit that
nobody recomputes. The app waits and **writes nothing**, not even that the
occurrence came round, because it did not. What ends the wait is the
**ended** sessions that arrive after the day: today's session is still open and
proves nothing about the day before (on 17 September 2026 at 10:06 the 16th was
empty and the 17th was there, at a price that kept moving until 18:00). After
three ended sessions that all have their close, the day asked for is taken as
one on which that security did not trade (a holiday, a weekend, or a gap in the
feed that will never fill), and the purchase happens at the first ended session
after it, never at the one before: a recurring order cannot execute before the
day it exists. Three is a policy, not a measurement; `prices._close_on` says
between what and what it sits.

**Currency is designed; locale happened.** Everything is converted into one
base currency (yours to choose, the euro by default) before it is shown; how
that number is punctuated depends on who reads it. The converter is the only
place that can add two currencies: a property of a database model has no
session, so it **cannot do arithmetic on amounts**. It may return a count, a
date or a stored value, and nothing else. The rule is written in `models.py`,
where the property that broke it used to be: it once printed a total in Turkish
lira with a euro sign.

**The model proposes; you write.** Every write the chat makes arrives as a card
you confirm, and the write then takes the normal path (`crud`, `unit_of_work`,
`_columns`). The chat has no back door the forms lack, and the asymmetry
between what the analyst sees and what the chat sees is code, not a choice left
to the model.

**Stale is a fingerprint, not a clock.** Every proposal declares what it
depends on; confirming it computes that again and refuses with a 409 if
anything moved. No live price enters a fingerprint: a card does not expire
because the market moves, only because the data it was built on changed.

**A security is named in exactly one way:** through a card that carries
`reason`, `based_on` and `unknowns`, all required, and at most three in one
answer, only when you asked for several. A fund is named by an ISIN from the
catalogue; a share by a symbol that Yahoo lists as a share. The old instruction
("avoid recommending specific securities") was not removed: it changed form,
from an instruction into a structure.

## Known traps

Things that look as if they could be simplified, and cannot. Each is a bug that
has already been paid for.

- `GBp` is not `GBP`. The first is pence, the second pounds, and the difference
  is a factor of 100. The comparison is case-sensitive on purpose.
- The composition cache never gets worse. A refresh that falls from a source
  listing every holding (an issuer's own file) to one that publishes an
  extract, or that loses an axis (countries or sectors), does not replace the
  entry that has them.
- "Nobody answered" and "this instrument does not exist" are different
  statements. Presenting the first as the second teaches people to correct a
  ticker that was right. There is a third: "that day has no close", which says
  nothing about the network or the ticker.
- A row without prices and a missing row are the same fact seen through two
  windows. yfinance drops a session's row when every price is NaN **and** the
  volume is zero, and the last bar's volume is not always zero: measured on
  2026-09-17 on VWCE.MI, the same missing close of the 16th came back as a NaN
  row in one window and as no row in another. Dated closes are asked for with
  `keepna=True`, and the day asked for is looked up, never "the last row",
  which is the day before in disguise.
- The local date is not taken from `toISOString()`: that is the UTC date, which
  near midnight is another day.
- A cost is *known* only if every unit has a price that was paid. A mix of a
  recorded cost and a photograph's value is not a cost.
- For a position with a quantity, the currency of the **listing** rules, not
  that of the fund's share class: a class denominated in dollars can trade in
  euros.
- Full-text queries are quoted token by token, and the prefix asterisk goes
  *outside* the quotes: `"vangu"*` finds, `"vangu*"` finds nothing.
- The accumulating and the distributing twin are **always shown together**:
  they carry the same name and differ only in what they do with dividends, so
  showing one alone invites picking it without knowing there was a choice.
- Isolated figures use proportional digits, columns use tabular ones. Tabular
  digits at a large size look disjointed; their place is in a column.
