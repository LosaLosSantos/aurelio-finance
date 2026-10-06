/* What leaving a holding's ticker empty costs, said while the row is written.

   A position with no ticker is never priced, and one whose dividends the
   catch-up follows never has them collected: both read the ticker
   (analytics.py, pac.py), and both also need a quantity, so a position entered
   as a total loses neither for lacking one. Only a ticker fixes those two. The
   catch-up follows a stated Distributing and, since brief AF, a row with no
   policy, whose own dividend history decides (pac._follows_dividends), crypto
   excepted: without a ticker there is no history to read, so such a row is
   told that ANY dividends it pays are lost, since nobody knows yet whether it
   pays. The look-through takes a ticker or an ISIN (since ab72fbe), so that
   clause names both remedies: the ISIN is the easier to find, printed on every
   document a fund comes with.

   Only the costs that apply to the row as it stands are said, and nothing is
   said once a ticker is typed. The save is never blocked: a holding with no
   listing is a real thing to record. Rows already saved are left alone.

   No runtime imports, so `npm test` reaches it. */

export interface HoldingDraft {
  name: string;
  symbol: string;
  isin: string;
  mode: "total" | "qty";
  /** "acc", "dist", or "" when not chosen. */
  policy: string;
  /** The class the row will be saved with; a crypto row pays no dividend. */
  assetClass: string | null;
}

/** The shape the look-through accepts as an ISIN (composition._ISIN_RE),
    tested on the ISIN as the backend will store it: crud._clean_isin strips
    it, upper-cases it and removes its spaces, so "ie00 bf4r fh31" is looked
    through, and the page must not say it will not be. */
const ISIN = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/;

function asStored(isin: string): string {
  return isin.trim().toUpperCase().replaceAll(" ", "");
}

/** The line under the form, or null when a missing ticker costs this row
    nothing, or when there is a ticker or no name yet. */
export function absentTickerCost(d: HoldingDraft): string | null {
  if (!d.name.trim() || d.symbol.trim()) return null;
  // Price and dividends both need a quantity: said only for a row entered as
  // a quantity and a price, and only a ticker fixes them.
  const dividends =
    d.policy === "dist"
      ? " and its dividends will not be collected"
      : d.policy === "" && d.assetClass !== "crypto"
        ? " and any dividends it pays will not be collected"
        : "";
  const onlyTicker = d.mode === "qty" ? "without a ticker it will not be priced" + dividends : null;
  const lookedThrough = ISIN.test(asStored(d.isin));
  const tickerOrIsin = lookedThrough ? null : "without a ticker or an ISIN it will not be looked through";
  const said = [onlyTicker, tickerOrIsin].filter((c): c is string => c !== null).join(", and ");
  return said ? said[0].toUpperCase() + said.slice(1) + "." : null;
}
