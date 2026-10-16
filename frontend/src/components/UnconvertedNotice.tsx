import { unconvertedWords, type HistoryPoints, type NoticePart } from "./unconvertedWords";

/* Amounts a page counts as written, because no rate converts the code they are
   in (brief BA, the reader's decision D2 (c)).

   The other direction of the rule `OmissionsNotice` carries: nothing leaves the
   totals in silence, and nothing enters them in the wrong unit in silence
   either. The fallback itself is deliberate: an amount no source has priced is
   kept rather than dropped, because a total quietly short by a whole holding
   is as wrong as one quietly inflated, so what was missing is the saying so.

   Each block says first what the reader can act on: what kind of code it is (a
   typo, corrected on its row, or a currency no source quotes, which nobody can
   convert) and where it is written. Then how much of each figure on the page
   it is: each figure's own share, measured by the backend on the figure itself
   (`notice.py`), so a cost, a debt or a monthly flow says exactly what it adds
   there. Brief V printed a volume of rows here instead, and measured at
   279acf8 it matched no figure: 4,000.00 over 5 where 2,300.00 of the net
   worth was the code. The words are built in `unconvertedWords.ts`.

   Printed plainly, not through `money`: a figure under a currency symbol would
   read as a second total in the base, which is the misreading being warned
   about. The code sits after the digits. */
export function UnconvertedNotice({
  parts,
  baseCurrency,
  history,
}: {
  /** Each payload of the page, with the names its figures have on it. */
  parts: NoticePart[];
  /** The currency the page's figures are in: what the codes are counted as. */
  baseCurrency: string;
  /** The history's points, when the page draws it. */
  history?: HistoryPoints;
}) {
  const blocks = unconvertedWords(parts, baseCurrency, history);
  if (blocks.length === 0) return null;
  return (
    <div className="space-y-1.5 border-l-2 border-warn bg-warn-tint px-3 py-2 text-xs text-warn">
      {blocks.map((b) => (
        <div key={b.code}>
          <b>{b.kind}</b>
          {b.rows && <div className="text-ink-soft">{b.rows}</div>}
          {b.figures && <div className="text-ink-soft">{b.figures}</div>}
        </div>
      ))}
    </div>
  );
}
