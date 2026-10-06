import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getChainRun,
  listChainRuns,
  type ChainRun,
  type ChainRunSummary,
  type ChainStep,
} from "../api/chain";
import { RowsOrEmpty, Spinner, apiError, cardClass, locale, mdComponents } from "./ui";

/* The analyses, read at the width prose is read at.

   This is what is left of the Analyzer page, and it is left for the argument
   that put the chain on a page in the first place: the verdict is a DOCUMENT,
   and a document does not belong in a 32%-wide column. The running moved into
   the chat — a card that says what a minute and a few cents buy, confirmed,
   then watched step by step — and the reading stayed here, in the main column,
   opened from the card that produced it.

   It is not a tab. A tab is somewhere you go; this is somewhere a receipt sends
   you, and it names the run it was sent about rather than whatever ran most
   recently.

   AND NOW ALSO THE LIST OF THEM, because a receipt is a poor last resort. The
   app could already address any run by id, and had no way to say which runs
   there are — so a run whose card had scrolled out of a conversation, or whose
   conversation was deleted, stayed perfectly well stored and completely
   unreachable. The list is reached from the chat's own history, which is where
   the other kind of "before" already lives. */

const ROLE_LABEL: Record<string, string> = {
  analyst: "Analyst · sees only the numbers",
  confidant: "Knows you · has not seen the numbers",
  revision: "Analyst · answers the challenge",
  synthesis: "The answer",
};

/* What each run's `challenge` says, in the reader's words rather than the
   API's. Three answers and not two: a run that ended on no verdict line said
   nothing about the mandate, which is a different fact from a run whose
   confidant looked and found nothing to argue with. Folding the first into the
   second would let a formatting slip read as agreement — and agreement is
   precisely what the count below is watching for. */
const CHALLENGE: Record<string, { label: string; tone: string; title: string }> = {
  contested: {
    label: "contested",
    tone: "text-olive",
    title:
      "The confidant said it was challenging something that mattered, so the analyst was made to answer it",
  },
  fits: {
    label: "not contested",
    tone: "text-ink-faint",
    title: "The confidant read the findings and said they fit this person",
  },
  unstated: {
    label: "no verdict",
    tone: "text-warn",
    title:
      "That run ended on no verdict line, so it says nothing either way and is counted neither way",
  },
};

function StepBlock({ step }: { step: ChainStep }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="relative border-l border-rule pl-5">
      {/* the node on the timeline */}
      <span className="absolute -left-[4.5px] top-2.5 h-2 w-2 rounded-full bg-olive" />
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-0.5 text-left"
      >
        <span className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-olive">
          {ROLE_LABEL[step.role] ?? step.role}
        </span>
        <span className="font-display text-lg leading-tight text-ink">{step.title}</span>
        <span className="ml-auto shrink-0 text-xs text-ink-faint">
          {step.model}
          {step.duration_ms != null && ` · ${(step.duration_ms / 1000).toFixed(1)}s`}
          <span className="ml-2 text-ink-soft">{open ? "−" : "+"}</span>
        </span>
      </button>
      {open && (
        <div className="mt-2 max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {step.output}
          </ReactMarkdown>
        </div>
      )}
    </li>
  );
}

/* What the run cost and how long it took, from the steps themselves. Sums of
   measurements, never a forecast — and each one is dropped entirely when a step
   did not report it, because a total missing part of itself printed as a total
   is the one thing this app does not show. */
function measured(run: ChainRun): string[] {
  const out: string[] = [];
  const times = run.steps.filter((s) => s.duration_ms != null);
  if (times.length > 0) {
    out.push(`${Math.round(times.reduce((a, s) => a + (s.duration_ms ?? 0), 0) / 1000)}s`);
  }
  if (run.steps.length > 0 && run.steps.every((s) => s.cost != null)) {
    out.push(`$${run.steps.reduce((a, s) => a + (s.cost ?? 0), 0).toFixed(4)}`);
  }
  return out;
}

// The header both views share: the way out, and what you are looking at.
function Header({
  title,
  onList,
  onClose,
  children,
}: {
  title: string;
  /** Only from inside a run: the list is where `onList` goes, not where Back does. */
  onList?: () => void;
  onClose: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <button onClick={onClose} className="text-sm text-olive underline-offset-2 hover:underline">
        ‹ Back
      </button>
      {onList && (
        <button onClick={onList} className="text-sm text-olive underline-offset-2 hover:underline">
          All analyses
        </button>
      )}
      <h2 className="font-display text-2xl leading-none text-ink">{title}</h2>
      {children}
    </div>
  );
}

/* Every run there has been, and the one number that says whether the chain is
   doing the thing it charges for.

   THE COUNT IS THE POINT, and it is information about the tool rather than
   about the money — the kind this app gives about everything else. The chain
   buys a second opinion with an adversarial mandate; if the confidant never
   actually contests, those turns are an expensive way to agree with yourself,
   and until runs could be listed there was no way to know. It counts the
   confidant's OWN marker, not a reading of its tone, over exactly the runs
   printed underneath — so the sentence and the rows cannot come to disagree.

   NOTHING ACTS ON IT. A mandate that tightened itself when the count looked
   soft would be a prompt that changed without anybody deciding to change it,
   which is the opposite of what a record like this is for. The number is shown;
   the deciding stays with the reader. */
function RunList({ onOpen, onClose }: { onOpen: (id: number) => void; onClose: () => void }) {
  const [runs, setRuns] = useState<ChainRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listChainRuns()
      .then(setRuns)
      .catch((e) => setError(apiError(e, "The analyses could not be listed.")));
  }, []);

  const shown = runs ?? [];
  const pressed = shown.filter((r) => r.challenge === "contested").length;
  const fits = shown.filter((r) => r.challenge === "fits").length;
  const unstated = shown.length - pressed - fits;

  return (
    <div className="space-y-6">
      <Header title="Past analyses" onClose={onClose} />

      {shown.length > 0 && (
        <div className={cardClass + " space-y-2 p-4"}>
          <p className="text-sm text-ink">
            Over the last {shown.length} {shown.length === 1 ? "analysis" : "analyses"}, the
            colleague who knows you <span className="font-semibold">contested {pressed}</span> and
            let {fits} through
            {unstated > 0 && (
              <>
                {" "}
                ({unstated} ended on no verdict line and {unstated === 1 ? "is" : "are"} counted
                neither way)
              </>
            )}
            .
          </p>
          <p className="text-xs text-ink-faint">
            The chain is worth its wait only if that challenge bites, so this counts how often it
            said it did (the confidant&rsquo;s own word for each run, not a reading of its tone). A
            mandate that has gone soft shows up here as a column that never contests. Nothing acts
            on the number: a mandate that tightened itself would be a prompt that changed without
            anyone deciding to change it.
          </p>
        </div>
      )}

      <RowsOrEmpty
        loading={runs === null && error === null}
        error={error}
        empty={shown.length === 0}
        emptyText="Nothing has been analysed yet. Ask the chat for an analysis: it says what the wait and the few cents buy before anything starts."
      >
        {shown.map((r) => {
          const c = CHALLENGE[r.challenge] ?? CHALLENGE.unstated;
          return (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => onOpen(r.id)}
                className="flex w-full cursor-pointer flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-3 text-left transition hover:bg-tint"
              >
                <span className="text-ink">{new Date(r.created_at).toLocaleString(locale)}</span>
                <span className="text-xs text-ink-faint">
                  {r.step_count} steps
                  {r.revisions > 0 &&
                    ` · the analyst answered ${r.revisions} time${r.revisions > 1 ? "s" : ""}`}
                </span>
                <span className={"ml-auto shrink-0 text-xs " + c.tone} title={c.title}>
                  {c.label}
                </span>
                <span aria-hidden="true" className="shrink-0 text-ink-faint">
                  ›
                </span>
              </button>
            </li>
          );
        })}
      </RowsOrEmpty>
    </div>
  );
}

function OneRun({
  runId,
  onList,
  onClose,
}: {
  runId: number;
  onList: () => void;
  onClose: () => void;
}) {
  const [run, setRun] = useState<ChainRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRun(null);
    setError(null);
    getChainRun(runId)
      .then(setRun)
      .catch((e) => setError(apiError(e, "That analysis could not be loaded.")));
  }, [runId]);

  const verdict = run?.steps.find((s) => s.role === "synthesis");
  const earlier = run?.steps.filter((s) => s.role !== "synthesis") ?? [];
  const rounds = earlier.filter((s) => s.role === "revision").length;

  return (
    <div className="space-y-6">
      <Header title="The analysis" onList={onList} onClose={onClose}>
        {run && (
          <span className="text-xs text-ink-faint">
            {new Date(run.created_at).toLocaleString(locale)} · {run.steps.length} steps
            {rounds > 0
              ? ` · the analyst answered the challenge ${rounds} time${rounds > 1 ? "s" : ""}`
              : " · the challenge was not contested"}
            {measured(run).length > 0 && ` · ${measured(run).join(" · ")}`}
          </span>
        )}
      </Header>

      {error && <p className="text-down">{error}</p>}
      {!run && !error && <Spinner className="text-ink-soft" />}

      {run && verdict && (
        <div className={cardClass + " p-6"}>
          <p className="mb-3 text-[0.65rem] font-medium uppercase tracking-[0.14em] text-olive">
            What this means for you
          </p>
          <div className="max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {verdict.output}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {earlier.length > 0 && (
        <div className="space-y-3">
          {/* The interesting part is not the conclusion, it is where the
              analyst held its ground and where it gave way — which only exists
              in the record because the revision step is required to label every
              point REVISE or HOLD. */}
          <p className="text-sm text-ink-soft">How it got there</p>
          <ol className="space-y-5">
            {earlier.map((s) => (
              <StepBlock key={s.step_no} step={s} />
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

export default function Analysis({
  runId,
  onOpen,
  onClose,
}: {
  /** Which run to read, or null for the list of them. */
  runId: number | null;
  /** Open a run from the list, or null to go back to the list. */
  onOpen: (id: number | null) => void;
  /** Leave for the tab that is still underneath. */
  onClose: () => void;
}) {
  if (runId === null) return <RunList onOpen={onOpen} onClose={onClose} />;
  return <OneRun runId={runId} onList={() => onOpen(null)} onClose={onClose} />;
}
