/* What deleting a ledger entry does beyond the row, said before the press
   (brief AO).

   The catch-up writes some entries by itself: a PAC's buys, each for one
   occurrence of its plan, and the dividends of a position that follows them.
   Until brief AO, deleting one of them opened its occurrence or its day again,
   and the next start wrote it again: the occurrence bought again with what
   the deleted buy had left counted twice, the dividend recorded again. Now a
   deletion stays one (`crud.delete_transaction`, which the chat's card calls
   too): the PAC does not buy that occurrence again, its carry goes to zero,
   and the app does not record a dividend on that day again. The question the
   form asked said none of it.

   Pure, so `tests/ledgerDelete.test.ts` runs it under Node without a bundler.
   Dates go in as ISO strings; `fmt` is how the page prints them. */

/** The ledger fields this reads, as `TransactionRead` carries them. */
export type LedgerEntry = {
  id: number;
  kind: string;
  date: string;
  asset_name: string;
  symbol: string | null;
  institution_id: number | null;
  plan_id: number | null;
  plan_occurrence: string | null;
  ex_date: string | null;
};

const asIs = (iso: string) => iso;

/** The question the ledger's Delete asks about `entry`, with what follows
    from it. `rows` is the ledger, where the other buys of its occurrence are. */
export function deleteQuestion(
  entry: LedgerEntry,
  rows: LedgerEntry[],
  fmt: (iso: string) => string = asIs,
): string {
  const asked = `Delete ${entry.kind} "${entry.asset_name}" of ${fmt(entry.date)}?`;
  if (entry.kind === "buy" && entry.plan_id != null && entry.plan_occurrence) {
    const occurrence = fmt(entry.plan_occurrence);
    const others = rows.some(
      (t) =>
        t.id !== entry.id &&
        t.plan_id === entry.plan_id &&
        t.plan_occurrence === entry.plan_occurrence,
    );
    const settled = others
      ? `Its PAC's occurrence of ${occurrence} keeps its other buy, and this fund is not bought for it again.`
      : `Its PAC will not buy its occurrence of ${occurrence} again.`;
    return `${asked} ${settled} What the PAC carries goes to zero, and that money stays in the account's cash. If your broker did buy it, correct it with the figures from your statement instead.`;
  }
  if (entry.kind === "dividend" && entry.symbol && entry.institution_id != null) {
    // By its ex-date where the row keeps one (brief AZ): a dividend moved to
    // the day its money arrived is still the dividend of its ex-date.
    const which = entry.ex_date
      ? `the dividend of ${entry.symbol} with ex-date ${fmt(entry.ex_date)} at this account`
      : `a dividend of ${entry.symbol} at this account on ${fmt(entry.date)}`;
    return `${asked} The app will not record ${which} again. If your broker paid it, correct it with the credit from your statement instead.`;
  }
  return `${asked} Nothing brings it back.`;
}
