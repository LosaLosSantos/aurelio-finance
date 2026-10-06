import type { ReactNode } from "react";

/* The identity marks, drawn rather than imported: an SVG here has no licence
   attached, scales without a second asset, and inherits the ink colour.

   THE MARK — the libella, the Roman builder's plumb level, drawn as
   architecture rather than as a diagram: the beam across the top, the two eyes
   of the level below it, and the plumb line hanging dead centre between them.
   It is an instrument, not an emblem — it does not depict wealth, it depicts
   measurement, which is what this app actually does.

   The bob is the only thing in gold, and that is the whole argument of the
   mark: everything else is the apparatus, and the one part that carries the
   weight is the part that tells you the truth.

   Sizing is deliberate. The beam is wider than the eyes so the silhouette
   reads as a T and never as a face; the gap between the bob and each eye must
   survive down to ~1.5px, which is why the bob tapers instead of running
   parallel; and the shaft has to break well below the eyes or the mark closes
   into a solid blob at favicon size. */
const GOLD = "#c0a06a";

export function Mark({
  size = 28,
  className,
  accent = GOLD,
}: {
  size?: number;
  className?: string;
  accent?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 200 200"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <g fill="currentColor">
        <rect x="0" y="0" width="200" height="24" />
        <rect x="84" y="112" width="32" height="83" />
      </g>
      <g fill="none" stroke="currentColor" strokeWidth="17">
        <circle cx="41" cy="81" r="25" />
        <circle cx="159" cy="81" r="25" />
      </g>
      {/* the bob: wider where it meets the beam, tapering into the line */}
      <polygon points="78,50 122,50 116,113 84,113" fill={accent} />
    </svg>
  );
}

/* An empty page is the one place an illustration takes nothing from anyone —
   and the place a first-time user most needs a sentence telling them what to
   do next. */
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1.5 py-12 text-center">
      <Mark size={68} className="mb-1 text-olive opacity-40" />
      <p className="font-display text-xl leading-tight text-ink">{title}</p>
      <p className="max-w-[48ch] text-sm text-ink-soft">{children}</p>
    </div>
  );
}
