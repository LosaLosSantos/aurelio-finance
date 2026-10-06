/* Which bucket of a situation a holding is shown in — the one rule, and the one
   the situation's total depends on.

   The page's total is the sum of every holding it loaded. Each bucket's
   subtotal is the sum of the holdings handed to that bucket. The two agree only
   if every holding is handed to exactly one bucket, and they did not: the
   buckets matched a holding's class exactly, and five buckets know five
   classes while the backend knows eight. `fund_etf` is the one that mattered —
   every purchase a PAC makes is written with it (pac.py), and "Start from the
   last one" carries it into the next situation. Measured on a copy of the
   reader's database: "Total €1,900" over a page that listed €400, the other
   €1,500 a Vanguard fund counted and drawn nowhere, so it could be neither
   seen, corrected nor removed from its situation.

   So the rule is total by construction: a bucket names the classes it holds,
   and a class no bucket names — `cash`, `real_estate`, none at all, or one
   invented tomorrow — goes to Other. Never to no bucket.

   Pure, and with no runtime imports, so `tests/buckets.test.ts` runs it under
   Node without a bundler. */

export type Bucket = {
  /** The class a NEW holding typed into this bucket is written with. */
  cls: string;
  label: string;
  /** Every class this bucket shows. */
  holds: readonly string[];
};

// Investment buckets shown inside every dated situation. Cash is NOT a bucket
// — it lives in the live register at the institution level — which is also why
// a stray `cash` holding is shown in Other rather than hidden.
export const BUCKETS: readonly Bucket[] = [
  { cls: "equity", label: "Stocks & ETF", holds: ["equity", "fund_etf"] },
  { cls: "bond", label: "Bonds", holds: ["bond"] },
  { cls: "commodity", label: "Commodities", holds: ["commodity"] },
  { cls: "crypto", label: "Crypto", holds: ["crypto"] },
  { cls: "other", label: "Other", holds: ["other"] },
];

const FALLBACK = "other";

/** The bucket a holding of this class is shown in. Every class has one. */
export function bucketOf(assetClass: string | null | undefined): Bucket {
  const known = BUCKETS.find((b) => assetClass != null && b.holds.includes(assetClass));
  return known ?? BUCKETS.find((b) => b.cls === FALLBACK)!;
}

/** The holdings each bucket shows, in bucket order: every holding in exactly
    one list. */
export function sortIntoBuckets<H extends { asset_class?: string | null }>(
  holdings: readonly H[],
): { bucket: Bucket; holdings: H[] }[] {
  return BUCKETS.map((bucket) => ({
    bucket,
    holdings: holdings.filter((h) => bucketOf(h.asset_class) === bucket),
  }));
}

/** The class a saved holding is written with. A new one takes its bucket's; an
    edited one keeps its own, because a bucket that shows several classes must
    not rename the ones it did not write — an ETF corrected in "Stocks & ETF"
    stays `fund_etf`, and a `cash` row corrected in Other stays `cash`. */
export function classOnSave(bucket: Bucket, editing: { asset_class?: string | null } | null): string | null {
  return editing ? (editing.asset_class ?? null) : bucket.cls;
}
