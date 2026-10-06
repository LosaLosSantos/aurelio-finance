/* Where a link out of an explanation can land.

   The account page groups by ACCOUNT. The forms that fill it group by KIND —
   income beside income, buys beside buys — because entering ten expenses in a
   row is a real workflow and it would be ruined by scattering them across the
   accounts they are paid from. Both groupings are right, and neither is going
   away.

   So the cash register's sentence stops pretending it owns the numbers it
   prints. Each value below is a section that is the SOLE home of one term in
   it: the place that number is typed, and the only place it can be corrected.
   A `Focus` is that destination, carried from the account page to the page
   that owns the term. */
export type Focus = "income" | "expenses" | "transfers" | "ledger";
