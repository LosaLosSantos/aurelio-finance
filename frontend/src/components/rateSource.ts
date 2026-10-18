/* Whose rate a figure was converted at, said wherever the rate's day is said
   (brief BA, the reader's decision D1).

   Every rate was the ECB's until then. A currency the ECB does not publish
   (TWD, AED, VND) is now converted at Yahoo's rate, its dollar pair crossed
   at the ECB's dollar of the same day, so a day alone no longer says whose
   rate it was: "FX ECB 15/10" stands beside "FX Yahoo 15/10", and a ledger
   row or a transfer says "at the Yahoo rate of". The backend says whose
   (`fx_source`, `fx_yahoo_as_of`); these are its words.

   Pure, so tests/rateSource.test.ts runs it under Node. */

/** The Portfolio's line of where its rates came from, or null for none. */
export function fxProvenance(
  ecb: string | null | undefined,
  yahoo: string | null | undefined,
  fmt: (iso: string) => string,
): string | null {
  const said = [ecb ? `FX ECB ${fmt(ecb)}` : null, yahoo ? `FX Yahoo ${fmt(yahoo)}` : null];
  const line = said.filter(Boolean).join(" · ");
  return line === "" ? null : line;
}

/** "at the ECB rate of <day>" or "at the Yahoo rate of <day>", for a sum
    fixed on its day. A row the API returns says whose; a rate with no source
    said is the ECB's, as every rate was before brief BA. */
export function rateLine(day: string, source: string | null | undefined): string {
  return `at the ${source ?? "ECB"} rate of ${day}`;
}
