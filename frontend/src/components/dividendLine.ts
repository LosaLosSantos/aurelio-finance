/* What a holding's line says about its dividends: one rule, for Records and
   Portfolio alike.

   A stated policy is said in a reader's words ("Accumulating", "Distributing").
   The stored token stays "acc" / "dist", because pac.py reads it: a stated
   Distributing is always asked about, a stated Accumulating never.

   An EMPTY policy is no longer "nothing". Since brief AF the catch-up follows
   such a holding's own dividend history, because a share has no policy to
   choose (it pays or it does not), and the line says when Yahoo last listed a
   dividend for it, from the answers the catch-up keeps. No threshold: a share
   that stopped paying shows the day it stopped, which a word like
   "Distributing" would hide and a cut-off would decide for the reader. One that
   never paid says nothing.

   Pure, and with no runtime imports, so `tests/dividendLine.test.ts` runs it
   under Node without a bundler. */

/** A stated policy in the words a reader sees. A token this does not know is
    shown as stored rather than dropped. */
export function policyWord(p: string | null | undefined): string | null {
  if (!p) return null;
  return p === "acc" ? "Accumulating" : p === "dist" ? "Distributing" : p;
}

/** What the line says: the stated policy, or, with none stated, the last
    dividend the holding's own history lists. */
export function dividendWord(
  policy: string | null | undefined,
  lastDividend: string | null | undefined,
): string | null {
  return policyWord(policy) ?? (lastDividend ? `last dividend ${lastDividend}` : null);
}
