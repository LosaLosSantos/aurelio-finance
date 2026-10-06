import axios from "axios";
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { Components } from "react-markdown";
import { EDGE, nextOpen, placePanel } from "./explain";
import { localDay } from "./calendarDays";

// Shared UI building blocks + style constants, reused across feature tabs.

// Direction "Editoriale": crisp 1px edges, warm surfaces, olive accent.
// No soft shadows: depth comes from hairlines, as in the design specimen.
// The exception is what floats above the page (the instrument picker's list,
// a "?"'s panel), where a hairline alone cannot say which surface is on top.
export const inputClass =
  "rounded-sm border border-rule bg-surface px-3 py-2 text-sm outline-none transition focus:border-olive focus:ring-1 focus:ring-olive";
export const btnClass =
  "rounded-sm bg-olive px-4 py-2 text-sm font-medium tracking-wide text-white transition hover:bg-olive-deep disabled:opacity-50";
export const cardClass = "rounded-sm border border-rule bg-surface";

/* The id of the one `<datalist>` of currency codes, rendered once in the app
   shell and referenced by every currency box through `list=`. Shared here
   because a literal repeated at eleven inputs and one datalist is a typo away
   from a box with no suggestions and nothing saying so. */
export const CURRENCY_LIST = "currency-codes";

// The reader's locale and the per-currency formatter live in ./money, which
// has no React in it; re-exported here so the import every page already has
// keeps working.
export { locale, money } from "./money";

/* CONVERTED figures — every total the backend has already turned into the
   base currency — are printed in the base THE PAYLOAD DECLARES:
   `money(summary.base_currency).format(summary.net_worth)`.

   There used to be an `eur` and a `eurCents` here, formatters with the euro
   built in at import time. The base is the reader's database's now, and a
   formatter that knew it in advance would be a module-level guess: a tab left
   open across a change of base would print the new unit beside numbers
   computed in the old one. Taking the unit from the response the number came
   in means a figure and its unit always arrive together — the rule 0bf262b
   paid for, with a name that can no longer carry it.

   The currency is DESIGNED and the locale is ACCIDENTAL, as before: a German
   and an Italian read the same number punctuated differently. A figure the
   reader TYPED is in its row's currency, `money(row.currency)`. And for the
   few figures where the cents ARE the fact — a carried remainder smaller than
   one unit, a balance compared with a spend — `money(code, "cents")`. */

/* There is no new-row currency here any more. It was EUR, written into every
   form that could not tell what a row was in, and it was true only while EUR
   was the only base. A form now proposes the currency of the account the row
   belongs to (`proposedCurrency.ts`), and a row with no account — a debt, a
   goal, a real asset — proposes the base the reader chose, which it reads from
   the backend with its own data. The box shows the proposal, and what the
   reader types in it wins. */

// Today's date in LOCAL time as YYYY-MM-DD. Never use toISOString() for this:
// it returns the UTC date, which near midnight differs from the user's (and
// the backend's) local date and silently breaks date comparisons. The one
// definition is `calendarDays.localDay`, which the situation's age counts from.
export function todayISO(): string {
  return localDay(new Date());
}

// A fund's dividend policy in the words a reader sees: kept in `dividendLine`,
// beside what a line says when no policy is stated, so the two cannot drift.
export { policyWord } from "./dividendLine";

// What the backend actually said about a failed request, or `fallback` when it
// said nothing usable.
//
// The backend writes its refusals to be read by a person — "Broker B already
// has a situation on 2026-02-01" — and every call site used to throw them away
// in a bare `catch { setError("Save failed.") }`. The reader got a sentence
// naming the verb and nothing else, and so did whoever was debugging. The
// fallback is what we say when there is genuinely nothing better, not the
// first thing we reach for.
export function apiError(e: unknown, fallback: string): string {
  if (!axios.isAxiosError(e)) return fallback;

  // Nothing answered at all. "The server refused this" and "there was no
  // server" are different claims, and reporting the second as the first sends
  // someone off to correct a request that was fine — the same distinction the
  // backend keeps between MarketUnreachable and PriceError.
  if (!e.response) return "The backend did not answer. Is it running on :8000?";

  const detail = (e.response.data as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();

  // 422: FastAPI validates the body and returns one entry per offending field.
  // String()-ing that array reads "[object Object]", which is a worse message
  // than the fallback it replaced — so it is unpacked rather than stringified.
  if (Array.isArray(detail)) {
    const fields = detail
      .map((d) => {
        const { loc, msg } = d as { loc?: unknown[]; msg?: unknown };
        if (typeof msg !== "string") return null;
        const field = Array.isArray(loc) && loc.length ? String(loc[loc.length - 1]) : null;
        return field ? `${field}: ${msg}` : msg;
      })
      .filter((line): line is string => line !== null);
    if (fields.length) return fields.join("; ");
  }

  // A 500 comes back as plain "Internal Server Error" with no detail, which
  // names the failure no better than the caller's own fallback does.
  return fallback;
}

/* Motion that claims only that something is happening — which, unlike a
   progress bar, is a claim we can always stand behind. Stops for readers who
   asked their OS for less motion. */
// How a model's Markdown is drawn — Tailwind classes per element, no typography
// plugin. It lived in Advisor.tsx, which was a page; it is here now because it
// was never that page's, and the two things that render prose in this app are
// the chat panel and the analysis reader.
export const mdComponents: Components = {
  h1: ({ node: _n, ...p }) => <h1 className="mb-3 mt-2 text-xl font-semibold text-ink" {...p} />,
  h2: ({ node: _n, ...p }) => <h2 className="mb-2 mt-6 border-b border-hair pb-1 text-lg font-semibold text-ink" {...p} />,
  h3: ({ node: _n, ...p }) => <h3 className="mb-1.5 mt-4 text-base font-semibold text-ink" {...p} />,
  p: ({ node: _n, ...p }) => <p className="my-2" {...p} />,
  ul: ({ node: _n, ...p }) => <ul className="my-2 list-disc space-y-1 pl-5" {...p} />,
  ol: ({ node: _n, ...p }) => <ol className="my-2 list-decimal space-y-1 pl-5" {...p} />,
  strong: ({ node: _n, ...p }) => <strong className="font-semibold text-ink" {...p} />,
  a: ({ node: _n, ...p }) => <a className="text-olive underline" target="_blank" rel="noreferrer" {...p} />,
  blockquote: ({ node: _n, ...p }) => (
    <blockquote className="my-3 rounded-r-lg border-l-4 border-warn bg-warn-tint px-3 py-2 text-ink" {...p} />
  ),
  code: ({ node: _n, ...p }) => <code className="rounded bg-tint px-1 py-0.5 font-mono text-[13px]" {...p} />,
  pre: ({ node: _n, ...p }) => (
    <pre className="my-3 overflow-x-auto rounded-sm bg-ink p-3 text-xs text-ground [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-ground" {...p} />
  ),
  hr: ({ node: _n, ...p }) => <hr className="my-4 border-rule" {...p} />,
  table: ({ node: _n, ...p }) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm" {...p} />
    </div>
  ),
  th: ({ node: _n, ...p }) => <th className="border-b border-rule py-1.5 pr-4 font-semibold text-ink" {...p} />,
  td: ({ node: _n, ...p }) => <td className="border-b border-hair py-1.5 pr-4 align-top" {...p} />,
};

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      className={"inline-block h-3.5 w-3.5 animate-spin motion-reduce:animate-none " + (className ?? "")}
    >
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" opacity="0.3" />
      <path d="M14 8a6 6 0 0 0-6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* Whole seconds since `startedAt`, ticking once a second while it is set.
   Elapsed time is a FACT about the wait, which is what lets it stand where a
   forecast ("up to a minute") could not: at 20 seconds this is normal, at 90 it
   is not, and the reader can tell the two apart without being promised
   anything. `null` means nothing is running and the clock does not tick. */
export function useElapsedSeconds(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  if (startedAt === null) return 0;
  // `now` can predate the click for the first second — the interval has not
  // fired yet — so the clock starts at 0, never below it.
  return Math.max(0, Math.round((now - startedAt) / 1000));
}

export type Crumb = { label: string; active: boolean; onClick: () => void };

export function Breadcrumb({ items }: { items: Crumb[] }) {
  // One crumb is not a position: it only repeated the section's own heading
  // ("Institutions" over "Institutions"), so it is not drawn.
  if (items.length < 2) return null;
  return (
    <nav className="flex flex-wrap items-center gap-1 text-sm text-ink-soft">
      {items.map((c, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <span className="text-ink-faint">/</span>}
          <button
            onClick={c.onClick}
            aria-current={c.active ? "page" : undefined}
            className={
              "rounded px-1.5 py-0.5 " +
              (c.active ? "font-semibold text-ink" : "hover:text-olive")
            }
          >
            {c.label}
          </button>
        </span>
      ))}
    </nav>
  );
}

/** What a "?" explains: the question is its accessible name ("How does a PAC
    work?", never a bare "?"), the text is what it opens. */
export type Explain = { question: string; text: string };

/* A "?" and the panel it opens, drawn together. The panel floats above the
   page, attached to its "?", and opening or closing it moves nothing else.

   It opens on a press only (click, tap, Enter or Space; never hover, and no
   `title`), because a "?" helps only a reader who knows they have a question.
   So it holds definitions and rules read once, never a warning, a consequence
   or where a number comes from: a reader about to make a mistake does not know
   to press it. When it opens and closes is `nextOpen`'s decision, and no one
   else's.

   The panel is a `manual` popover. The browser draws an open one in the top
   layer, above the whole page, where no `overflow` can clip it and no z-index
   can cover it, and hides a closed one. That is all `manual` asks of it. An
   `auto` popover also closes itself, on Escape, on a press outside (when the
   press is released, where ours closes on the press) and whenever another
   one opens, without React knowing: its "?" would still say open, and the
   rules would have two owners.

   The top layer changes where the panel is drawn, not where it is in the
   document. It stays right after its button, so a screen reader reads the
   text straight after the "?", and `aria-controls` always names something.

   It is placed from the button's box (`placePanel`) in page coordinates:
   `absolute`, against the page rather than the window, so a scroll carries it
   along with its "?" and no code runs. Anything else that moves the "?" while
   it is open (a resize, the catch-up banner arriving at the top) is caught by
   a check at each frame while it is open. A scroll changes nothing that check
   compares, so the panel never jumps from under the "?" to over it while the
   reader scrolls. It never reaches past the window's edges, so it cannot
   widen a 390px page.

   Never give the panel a `display` class: the browser hides a closed popover
   with `display: none`, and an author's `display` would show it, unplaced. */
export function Explainer({ question, text }: Explain) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const ours = (t: EventTarget | null) =>
      t instanceof Node && !!(buttonRef.current?.contains(t) || panelRef.current?.contains(t));
    function onPointer(e: PointerEvent) {
      setOpen((o) => nextOpen(o, { kind: "pointer", inside: ours(e.target) }));
    }
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      // Focus goes back to the button only if it was ours: an Escape pressed
      // with the cursor elsewhere closes the panel without taking the cursor.
      const was = ours(document.activeElement);
      setOpen((o) => nextOpen(o, { kind: "escape" }));
      if (was) buttonRef.current?.focus();
    }
    // Where focus went. `focusin` names the element that gained it, wherever
    // it came from. Focus going to no element at all (a press on the panel's
    // text, the window losing focus) is a `focusout` with no `relatedTarget`,
    // and `focusin` never reports it. A `focusout` towards an element is
    // followed by that element's `focusin`, so it is left to that.
    function onFocusIn(e: FocusEvent) {
      setOpen((o) => nextOpen(o, { kind: "focus", to: ours(e.target) ? "inside" : "outside" }));
    }
    function onFocusOut(e: FocusEvent) {
      if (e.relatedTarget === null) setOpen((o) => nextOpen(o, { kind: "focus", to: "nothing" }));
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, [open]);

  // A layout effect, so the panel is shown and placed before the browser
  // paints: it never appears for a frame in the wrong place.
  useLayoutEffect(() => {
    const button = buttonRef.current;
    const panel = panelRef.current;
    if (!open || !button || !panel) return;
    const root = document.documentElement;
    // `clientWidth` and `clientHeight` leave out a scrollbar; `innerWidth`
    // would count it as room.
    const place = () => {
      panel.style.maxWidth = `min(68ch, ${root.clientWidth - 2 * EDGE}px)`;
      panel.style.maxHeight = "";
      panel.style.left = "0px";
      panel.style.top = "0px";
      const { width, height } = panel.getBoundingClientRect();
      const at = placePanel(
        button.getBoundingClientRect(),
        { width, height },
        { width: root.clientWidth, height: root.clientHeight },
      );
      panel.style.maxHeight = at.maxHeight === null ? "" : `${at.maxHeight}px`;
      panel.style.left = `${at.left + window.scrollX}px`;
      panel.style.top = `${at.top + window.scrollY}px`;
    };
    // What a placement depends on: the "?"'s place in the PAGE (which a
    // scroll leaves as it is), the window's size, and the panel's own.
    const inputs = () => {
      const b = button.getBoundingClientRect();
      const p = panel.getBoundingClientRect();
      return [b.left + window.scrollX, b.top + window.scrollY, root.clientWidth, root.clientHeight, p.width, p.height];
    };
    panel.showPopover();
    place();
    let last = inputs();
    let frame = requestAnimationFrame(function check() {
      const now = inputs();
      // A pixel of slack: a fractional scroll offset can move the sum by
      // less than that without anything having moved.
      if (now.some((v, i) => Math.abs(v - last[i]) > 1)) {
        place();
        last = inputs();
      }
      frame = requestAnimationFrame(check);
    });
    return () => {
      cancelAnimationFrame(frame);
      if (panel.matches(":popover-open")) panel.hidePopover();
    };
  }, [open]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-label={question}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => nextOpen(o, { kind: "press" }))}
        className={
          "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-olive " +
          (open ? "border-olive text-olive" : "border-rule text-ink-soft hover:border-olive hover:text-olive")
        }
      >
        ?
      </button>
      {/* The browser's own popover style centres it in the window with a
          medium border; `absolute inset-auto m-0` undo that, so `left` and
          `top` place it. `overflow-y-auto` is for the very short window,
          where its height is capped and its text scrolls inside it. */}
      <div
        ref={panelRef}
        id={id}
        popover="manual"
        className="absolute inset-auto m-0 overflow-y-auto rounded-sm border border-rule bg-ground p-3 text-sm text-ink-soft shadow-md"
      >
        {text}
      </div>
    </>
  );
}

export function Section({
  title,
  aside,
  hint,
  note,
  explain,
  children,
}: {
  title: string;
  /** Put on the title ROW, right-aligned: the one figure this section is
      about, where a reader looking for it already looks. The cash register
      states its projected balance in exactly that spot, so a second section
      answering the other half of "how much is here" has to use the same spot,
      or the two numbers cannot be read together. */
  aside?: ReactNode;
  /** One sentence: what this section is FOR. Read every time, so keep it short. */
  hint?: string;
  /** The mechanics, one step quieter — read once, then skipped forever.
      Separating the two is the whole point: a 90-word paragraph above a table
      is not read carefully, it is skipped, and it takes the space of the one
      line that would have been. */
  note?: string;
  /** A definition or a rule read once, behind a "?" beside the title. Never a
      warning, a consequence or where a number comes from: those stay in
      `hint` or `note`, in view. */
  explain?: Explain;
  children: ReactNode;
}) {
  const heading = <h2 className="font-display text-2xl leading-tight text-ink">{title}</h2>;
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          {explain ? (
            <div className="flex items-center gap-2">
              {heading}
              <Explainer {...explain} />
            </div>
          ) : (
            heading
          )}
          {aside}
        </div>
        {hint && <p className="max-w-[68ch] text-sm text-ink-soft">{hint}</p>}
        {note && <p className="max-w-[76ch] text-xs text-ink-faint">{note}</p>}
      </div>
      {children}
    </div>
  );
}

export function RowsOrEmpty({
  loading,
  error,
  empty,
  emptyText,
  children,
}: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyText: string;
  children: ReactNode;
}) {
  if (loading) return <p className="text-ink-soft">Loading…</p>;
  if (error) return <p className="text-down">{error}</p>;
  if (empty) return <p className="text-ink-soft">{emptyText}</p>;
  return (
    <ul className={cardClass + " divide-y divide-hair overflow-hidden"}>
      {children}
    </ul>
  );
}

export function Row({
  onClick,
  onEdit,
  onDelete,
  onRefresh,
  refreshing,
  title,
  subtitle,
  detail,
  note,
  badge,
  value,
}: {
  onClick?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onRefresh?: () => void;
  refreshing?: boolean;
  title: string;
  subtitle?: string;
  /** A fact that must survive a narrow window. `subtitle` truncates, which is
      right for a list of attributes and wrong for anything the reader is
      entitled to see — it gets its own line and is never clipped. */
  detail?: string;
  /** The note stored on the record, exactly as stored: the reader's own words,
      or a stamp the app wrote saying where the row came from. Never clipped,
      for `detail`'s reason and one more: there is no box to read it in, so
      this line is the only place on the page it exists. Its line breaks are
      kept, and a long word wraps rather than widening the row.

      It sits under the whole row, not in the text column. On a phone the
      figure and the badge can squeeze that column to a few pixels (at 390px
      a debt's own name already has 2), and a note drawn inside it stood one
      letter per line. Outside the button, it is also not read out as part of
      the row's name. */
  note?: string | null;
  badge?: string | null;
  value?: string;
}) {
  const content = (
    <>
      <div className="min-w-0">
        <div className="truncate font-medium text-ink">{title}</div>
        {subtitle && <div className="truncate text-xs text-ink-soft">{subtitle}</div>}
        {detail && <div className="text-xs text-ink-faint">{detail}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {value && <span className="tnum text-sm font-medium text-ink">{value}</span>}
        {badge && (
          <span className="rounded-full border border-olive px-2.5 py-0.5 text-[0.65rem] uppercase tracking-wider text-olive">
            {badge}
          </span>
        )}
        {onClick && <span className="text-ink-faint">›</span>}
      </div>
    </>
  );
  const innerCls =
    "flex min-w-0 flex-1 items-center justify-between gap-3 px-4 py-3 text-left";
  return (
    <li>
      <div className="flex items-center">
        {onClick ? (
          <button onClick={onClick} className={innerCls + " hover:bg-ground"}>
            {content}
          </button>
        ) : (
          <div className={innerCls}>{content}</div>
        )}
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={refreshing}
            aria-label="Refresh price"
            title="Refresh price from the market"
            className="shrink-0 px-2 py-3 text-ink-faint transition hover:text-up disabled:opacity-50"
          >
            {refreshing ? "…" : "↻"}
          </button>
        )}
        {onEdit && (
          <button
            onClick={onEdit}
            aria-label="Edit"
            title="Edit"
            className="shrink-0 px-2 py-3 text-ink-faint transition hover:text-olive"
          >
            ✎
          </button>
        )}
        {onDelete && (
          <button
            onClick={onDelete}
            aria-label="Delete"
            title="Delete"
            className="shrink-0 px-3 py-3 text-ink-faint transition hover:text-down"
          >
            ✕
          </button>
        )}
      </div>
      {note && (
        <div className="whitespace-pre-line break-words px-4 pb-3 text-xs text-ink-faint">{note}</div>
      )}
    </li>
  );
}

/** A figure's name, in the band's small capitals. The Dashboard's meter wears
    it too, so one number is not called two things on two screens. */
export const statLabelClass = "text-[0.65rem] font-medium uppercase tracking-[0.14em] text-ink-soft";

/** One number, one name, one definition: the Cash flow page and the
    Dashboard's meter show the same `savings_rate`, and used to call it two
    different things. */
export const SAVINGS_RATE: Explain = {
  question: "What is the savings rate?",
  text: "Share of monthly income left after expenses.",
};

export function StatCard({
  label,
  value,
  valueClass,
  note,
  explain,
}: {
  label: string;
  value: string;
  valueClass?: string;
  /** One quiet line under the figure, for the caveat the figure cannot carry
      itself — how much of it is measured rather than remembered. */
  note?: string;
  /** What the figure's name means, behind a "?" beside it. */
  explain?: Explain;
}) {
  const name = <div className={statLabelClass}>{label}</div>;
  // Editorial data band, not a card: a top rule and generous air, so a row of
  // these reads as one continuous band of figures (per the design specimen).
  return (
    <div className="border-t border-rule pt-3">
      {explain ? (
        <div className="flex items-center gap-2">
          {name}
          <Explainer {...explain} />
        </div>
      ) : (
        name
      )}
      {/* Proportional figures on purpose: tabular digits make a standalone
          value look loose at display sizes. Tabular belongs in columns. */}
      <div
        className={"mt-1.5 font-display text-3xl leading-none " + (valueClass ?? "text-ink")}
      >
        {value}
      </div>
      {note && <div className="mt-1 text-[0.7rem] leading-snug text-ink-faint">{note}</div>}
    </div>
  );
}

export function CancelButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-sm px-3 py-2 text-sm text-ink-soft hover:text-ink"
    >
      Cancel
    </button>
  );
}

/** The submit button, plus the Cancel that only exists while editing. */
export function EditorButtons({
  editing,
  submitting,
  onCancel,
  addLabel = "Add",
  saveLabel = "Save",
}: {
  editing: boolean;
  submitting: boolean;
  onCancel: () => void;
  addLabel?: string;
  saveLabel?: string;
}) {
  return (
    <>
      <button className={btnClass} disabled={submitting}>
        {submitting ? "..." : editing ? saveLabel : addLabel}
      </button>
      {editing && <CancelButton onClick={onCancel} />}
    </>
  );
}
