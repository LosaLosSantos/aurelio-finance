import type { Ref } from "react";
import { btnClass } from "./ui";

/* The strip at the top of the Profile tab (brief BC): the path's three parts,
   the one the reader is in, how far each is answered, what is not saved yet,
   and the one save. It stays at the top of the window while the path is
   read, so the save is never screens away (at 390 it was 5.4 windows down),
   and it leaves with the path: the Theme card after it is not saved.

   Nothing is hidden: every part is on the page, and a part's button only
   scrolls to it. Below 640px the parts the reader is not in show their
   number alone; their words stay in the button's name. What a save said
   (refused, or held back by the reader) is said here too, where the press
   was. */
export default function PathStrip({
  stripRef,
  parts,
  current,
  onGo,
  unsaved,
  saved,
  saving,
  onSave,
  said,
}: {
  /** The strip's own box: where a part counts as reached. */
  stripRef: Ref<HTMLDivElement>;
  parts: { key: string; title: string; status: string }[];
  current: number;
  onGo: (index: number) => void;
  unsaved: string | null;
  saved: boolean;
  saving: boolean;
  onSave: () => void;
  /** What the last save could not do, in the backend's words, or what the
      reader held back; null when there is nothing to say. */
  said: { tone: "refused" | "held"; text: string } | null;
}) {
  return (
    <div ref={stripRef} className="sticky top-0 z-20 -mx-1 border-b border-rule bg-ground px-1 pb-2 pt-3">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <nav aria-label="The profile's parts" className="min-w-0">
          <ol className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
            {parts.map((p, i) => {
              const here = i === current;
              const away = here ? "" : "sr-only sm:not-sr-only";
              return (
                <li key={p.key}>
                  <button
                    type="button"
                    onClick={() => onGo(i)}
                    aria-current={here ? "step" : undefined}
                    className={
                      "border-b-2 pb-1 text-left text-sm transition " +
                      (here ? "border-olive text-ink" : "border-transparent text-ink-soft hover:text-ink")
                    }
                  >
                    <span className="tnum font-semibold">{i + 1}</span>
                    <span className={away}> {p.title}</span>
                    <span className={"text-xs text-ink-soft " + away}> · {p.status}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {unsaved ? (
            <span className="text-xs text-warn">{unsaved}</span>
          ) : (
            saved && <span className="text-sm text-up">Saved ✓</span>
          )}
          <button type="button" onClick={onSave} disabled={saving} className={btnClass}>
            {saving ? "Saving…" : "Save profile"}
          </button>
        </div>
      </div>
      {said && (
        <p role="alert" className={"mt-2 max-w-[76ch] text-xs " + (said.tone === "refused" ? "text-down" : "text-warn")}>
          {said.text}
        </p>
      )}
    </div>
  );
}
