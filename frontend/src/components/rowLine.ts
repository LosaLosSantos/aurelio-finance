/* The line under a flow's or a plan's name, which Cash flow's lists and the
   PAC's both write. Moved out of CashFlow.tsx when the PAC moved to Portfolio
   (brief BD).

   Pure, no runtime imports. */

/** The parts that are there, joined; undefined when none is. */
export function subtitle(parts: (string | null | undefined)[]): string | undefined {
  const kept = parts.filter(Boolean);
  return kept.length ? kept.join(" · ") : undefined;
}

/** When a flow or a plan runs, as far as it says. */
export function dateRange(start: string | null, end: string | null): string | undefined {
  if (start && end) return `${start} → ${end}`;
  if (start) return `from ${start}`;
  if (end) return `until ${end}`;
  return undefined;
}
