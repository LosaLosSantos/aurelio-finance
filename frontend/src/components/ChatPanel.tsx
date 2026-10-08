import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  deleteConversation,
  getChatModels,
  getConversation,
  listConversations,
  streamChat,
  type ChatBlock,
  type ChatToolBlock,
  type ChatSourcesBlock,
  type ChatCardBlock,
  type ChatPage,
  type ChatPageBlock,
  decideCard,
  type ChatConversation,
  type ChatMessage,
  type ChatModels,
  type ChatStepEvent,
} from "../api/chat";
import { Spinner, apiError, locale, mdComponents } from "./ui";
import {
  FOLLOWING,
  onContent,
  onScroll,
  onSend,
  type Follow,
  type Pane,
} from "./followStream";
import { linkOf, withSource, type Link, type WebPage } from "./webSources";
import { withDecided } from "./cardDecided";
import { lineText } from "./cardFields";

/* The chat that reads.

   A PANEL, not a tab, and on the LEFT: ask "how am I doing on the house goal?",
   get an answer, and go and look — if the chat were a tab, looking would mean
   leaving the conversation. It is rendered above the tabs in App.tsx and never
   unmounted (closed means zero width), so it follows you across pages. Open,
   it reads as primary; closed, the content does.

   What a message IS. Not a string: a role and a list of blocks, each with a
   `kind` — text, the model's thinking, a tool it consulted, a card it proposed.
   A suggested instrument from the catalogue is a new kind beside those, not a
   rewrite of what a message is. If you find yourself treating `blocks` as one
   string, stop.

   Where the conversation lives: on the server, as a record, the way a chain
   run does. The browser keeps only WHICH conversation is open and which model
   was picked (sessionStorage), so a reload lands where you were; the words
   themselves are fetched. The history list is the same table read backwards. */

type Message = {
  id: string;
  role: "user" | "assistant";
  blocks: ChatBlock[];
  /** Finished steps of a long tool, while it is running. Client-only, and
      deliberately not a block: nothing on the server stores these, because the
      run they report IS a record and the card that proposed it is the receipt.
      They go when the conversation is reloaded, which is right — by then the
      thing they were narrating has a document of its own. */
  steps?: ChatStepEvent[];
  /** When it was created (ms since epoch). For an answer, the moment the
      question was sent — the clock the reader watches until the first token. */
  at: number;
  /* Assistant messages only. `streaming` while the answer arrives; then one of
     four ends, because from the bytes alone they look alike and the reader has
     to be able to tell them apart: `done` is a finished answer, `error` is the
     backend saying why it stopped, `cut` is a connection that closed with
     neither — the answer broke off — and `aborted` is the reader's own Stop.
     The server stores the first three; a Stop comes back as `cut` after a
     reload, because the server cannot tell the two apart. */
  status?: "streaming" | "done" | "error" | "cut" | "aborted";
  detail?: string | null;
  model?: string | null;
};

const STORAGE_KEY = "aurelio.chat.v2";

type Stored = { conversationId: number | null; model: string | null };

function load(): Stored {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return { conversationId: null, model: null };
    const parsed = JSON.parse(raw) as Partial<Stored>;
    return { conversationId: parsed.conversationId ?? null, model: parsed.model ?? null };
  } catch {
    return { conversationId: null, model: null };
  }
}

function save(data: Stored) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    /* private window, quota: the chat still works, it just reopens on a blank
       conversation after a reload */
  }
}

function newMessage(
  role: Message["role"],
  blocks: ChatBlock[],
  status?: Message["status"],
): Message {
  const at = Date.now();
  return { id: at.toString(36) + Math.random().toString(36).slice(2, 8), at, role, blocks, status };
}

// A stored turn as the panel shows it. An assistant turn the server holds
// without a status was interrupted before it could be given one.
function fromStored(m: ChatMessage): Message {
  const status = m.role === "assistant" ? ((m.status as Message["status"]) ?? "cut") : undefined;
  return {
    id: String(m.id),
    role: m.role as Message["role"],
    blocks: m.blocks,
    at: Date.parse(m.created_at),
    status,
    detail: m.detail,
    model: m.model,
  };
}

function textOf(m: Message): string {
  return m.blocks
    .filter((b) => b.kind === "text")
    .map((b) => b.text)
    .join("");
}

/* The model's reasoning, folded. Open on its own only while it is the only
   thing there is — the seconds before the first word, which used to be a
   spinner — and folding itself the moment the answer begins, so the wait is
   spent watching the model think rather than watching a clock. The reader can
   reopen it afterwards, here and in the history: it is stored with the answer
   and never sent back to the model. */
function Thought({ text, thinking, answered }: { text: string; thinking: boolean; answered: boolean }) {
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? (thinking && !answered);
  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setManual(!open)}
        aria-expanded={open}
        className="inline-flex cursor-pointer items-center gap-1.5 text-[0.7rem] uppercase tracking-[0.14em] text-ink-faint hover:text-ink-soft"
      >
        {thinking && !answered ? <Spinner className="h-3 w-3" /> : null}
        {thinking && !answered ? "Thinking" : "Thoughts"}
        <span aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap border-l border-hair pl-3 text-xs leading-relaxed text-ink-faint">
          {text}
        </div>
      )}
    </div>
  );
}

/* A tool the model asked for, named where it happened. The name is shown raw
   and not through a table of friendlier labels, because a table is a second
   place the name lives and it drifts the moment a tool is renamed — the same
   argument that generates `schema.d.ts` instead of typing it.

   It never claims the tool SUCCEEDED. Success is not on the wire, so the line
   says "consulted" in every state and adds the failure only when there is one
   to add. A failure's reason arrives with the tool's event since brief AG, so
   the live line shows it as a reload would: a suggestion refused in a round
   that drew other cards is explained nowhere else. A live panel that is
   missing a fact is honest; a live panel that asserts a success it has not
   been told about is not. */
function ToolNote({ block, running }: { block: ChatToolBlock; running: boolean }) {
  return (
    <div className="my-2 border-l border-hair pl-3">
      <p className="flex items-baseline gap-2 text-[0.7rem] uppercase tracking-[0.14em] text-ink-faint">
        {running ? <Spinner className="h-3 w-3" /> : null}
        <span>{running ? "Consulting" : "Consulted"}</span>
        <span className="normal-case tracking-normal text-ink-soft">{block.name}</span>
      </p>
      {block.ok === false && (
        <p className="mt-0.5 text-xs text-down">{block.detail ?? "It did not answer."}</p>
      )}
    </div>
  );
}

/* The pages a web search found, listed where the search ran: above the words
   written from them, or at the end of a round that ended on one of the app's
   tools. They are what the search RETURNED, so the heading says found and not
   cited; the sentence that uses a page carries its own link. Each opens in a
   new tab and tells the site nothing about where the reader came from. */
function Sources({ block }: { block: ChatSourcesBlock }) {
  const links = block.pages.map(linkOf).filter((l): l is Link => l !== null);
  if (links.length === 0) return null;
  return (
    <div className="my-2 border-l border-hair pl-3">
      <p className="text-[0.7rem] uppercase tracking-[0.14em] text-ink-faint">Found on the web</p>
      <ul className="mt-1 space-y-0.5">
        {links.map((l) => (
          <li key={l.href} className="break-words text-xs leading-relaxed">
            <a
              href={l.href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-olive underline underline-offset-2"
            >
              {l.label}
            </a>
            <span className="text-ink-faint"> · {l.host}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* The one tool this panel knows by name, and it knows it for one reason: its
   result is not a row, it is the ADDRESS of a document. Every other card shows
   what was written and is done; this one has somewhere to send you. The name
   is here rather than in a table of labels — a table drifts the moment a tool
   is renamed — and what it unlocks is a link and nothing else. */
const ANALYZER = "run_analysis";

/* What the analyzer has finished, while it is finishing it. Three to six model
   calls and a minute of them, and the page this replaced would not fake a
   progress bar because it could not: the chain wrote nothing until all of it
   had finished, so "step 2 of 4" was a sentence nobody had been told. Each of
   these arrived as an event saying a step is done, so every line here is
   something that happened. */
function Steps({ steps, running }: { steps: ChatStepEvent[]; running: boolean }) {
  return (
    <div className="my-2 border-l border-hair pl-3">
      <p className="flex items-baseline gap-2 text-[0.7rem] uppercase tracking-[0.14em] text-ink-faint">
        {running ? <Spinner className="h-3 w-3" /> : null}
        <span>{running ? "Analyzing" : "Analyzed"}</span>
      </p>
      <ol className="mt-1 space-y-0.5">
        {steps.map((s) => (
          <li key={s.step_no} className="flex items-baseline gap-2 text-xs text-ink-soft">
            <span className="text-ink-faint">{s.step_no}.</span>
            <span className="min-w-0 flex-1">{s.label}</span>
            <span className="tnum shrink-0 text-ink-faint">
              {(s.duration_ms / 1000).toFixed(1)}s
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Fields({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <Fragment key={k}>
          <dt className="text-ink-faint">{k}</dt>
          <dd className="tnum text-ink">{v}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

/* A write the model PROPOSED. Nothing has happened: the model drafts the
   change, this shows exactly what it would do, and the write runs from the
   app's normal path only once the reader presses confirm.

   Two confirmations, and the difference is the domain's rather than a matter
   of taste: it is about REVERSIBILITY. An EVENT — a transaction, a dated
   valuation — is a dated claim, verifiable, undone by deleting it, so its
   fields are enough to decide on. Anything that OVERWRITES gets the diff, in
   the same band this app uses everywhere else for a thing you should read
   before you act: a snapshot, because changing it restates what that day said
   and re-anchors every projection after it, and a questionnaire answer, which
   carries no date and no history and after this simply says something else.
   What each of them COSTS differs, so the sentence above the table is the
   tool's and not this component's.

   The outcome stays on screen afterwards. A card that vanished when it was
   answered would leave a conversation in which somebody's records changed and
   nothing says so — a "done!" with no receipt — and a rejected one has to
   remain visible as rejected, or the same proposal simply comes round again. */
function Card({
  block,
  busy,
  onDecide,
  onOpenRun,
}: {
  block: ChatCardBlock;
  busy: boolean;
  onDecide: (decision: "confirm" | "reject") => void;
  onOpenRun: (runId: number) => void;
}) {
  const pending = block.outcome !== "confirmed" && block.outcome !== "rejected";
  const diff = block.diff ?? [];
  // The proposal's arguments and, once confirmed, what was written, both as
  // the server words them (`tools.present`): a label of the reader's for each,
  // nothing absent, no row id, no timestamp. Until brief AJ this printed the
  // arguments and the result raw, by their schema names, and a model's word
  // for nothing ("symbol null") passed for a value.
  const fields = block.fields ?? [];
  const receipt = block.receipt ?? [];
  // Only the one still waiting on the reader carries the accent. A settled
  // card is a record and should read as one; "Rejected" in the colour the app
  // uses for its own voice looked like approval of the opposite thing.
  const tone = pending ? "text-olive" : block.outcome === "confirmed" ? "text-ink-soft" : "text-ink-faint";
  return (
    <div className="my-3 rounded-sm border border-rule bg-surface p-3">
      <p className={"text-[0.65rem] font-medium uppercase tracking-[0.14em] " + tone}>
        {pending ? "Proposed" : block.outcome === "confirmed" ? block.done || "Recorded" : "Rejected"}
      </p>
      <p className="mt-1 text-sm text-ink">{block.title}</p>
      {/* What confirming COSTS that the fields do not show, in the proposing
          tool's own words. On a diff card it sits above the table; on a light
          one it is usually empty, and it is not empty for the analyzer, which
          is asking for a minute of the reader's attention and a few cents
          before it produces anything. Both figures are read off the last run. */}
      {block.confirmation !== "diff" && block.consequence && (
        <p className="mt-1 text-xs text-ink-faint">{block.consequence}</p>
      )}

      {block.confirmation === "diff" ? (
        <div className="mt-2 border-l-2 border-warn bg-warn-tint px-3 py-2 text-xs text-warn">
          {/* The sentence comes from the TOOL, because only the tool knows what
              confirming its own proposal costs: editing a snapshot moves every
              figure anchored after it, while replacing a questionnaire answer
              moves nothing and simply loses the previous one. This band used to
              say the first of those over both, which was right for the card it
              was written for and wrong for the next one. The fallback is the
              one thing true of every diff card there can be. */}
          <p>{block.consequence || "This replaces what is on record, and the old value does not come back."}</p>
          <table className="mt-2 w-full text-left">
            <thead>
              <tr className="text-[0.65rem] uppercase tracking-[0.14em]">
                <th className="font-medium">Field</th>
                <th className="font-medium">Now</th>
                <th className="font-medium">Would say</th>
              </tr>
            </thead>
            <tbody className="tnum">
              {diff.map((d) => (
                <tr key={d.field}>
                  <td className="pr-2 text-ink-soft">{d.field}</td>
                  {/* null is not zero: that day says nothing about this yet,
                      and the two must not look alike. */}
                  <td className="pr-2">{d.now ?? "not set"}</td>
                  <td>{d.proposed ?? "not set"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        fields.length > 0 && <Fields rows={fields.map((f) => [f.label, lineText(f, locale)])} />
      )}

      {block.result && (
        // Ruled off and labelled, because what was PROPOSED and what was
        // WRITTEN are two lists of fields and they can carry the same key
        // meaning different things — an argument called `value` above a
        // returned one is not a repeated row.
        <div className="mt-3 border-t border-hair pt-2">
          <p className="text-[0.65rem] uppercase tracking-[0.14em] text-ink-faint">Written</p>
          {block.tool === ANALYZER && typeof block.result.run_id === "number" && (
            // The one result that is an address rather than a row. The verdict
            // is a document and this column is 32% wide, which was the argument
            // for keeping the chain on a page — so the page did not disappear,
            // it became somewhere this sends you.
            <button
              type="button"
              onClick={() => onOpenRun(block.result?.run_id as number)}
              className="mt-1 cursor-pointer text-sm text-olive underline-offset-2 hover:underline"
            >
              Read it in full ›
            </button>
          )}
          {/* The receipt the tool words: what was written that the card's own
              lines cannot show (the amount worked out, the day of its rate,
              the day it joined the watchlist). The result itself stays on the
              block, raw, for the model and for the link above. */}
          {receipt.length > 0 && (
            <Fields rows={receipt.map((f) => [f.label, lineText(f, locale)])} />
          )}
        </div>
      )}

      {pending && (
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide("confirm")}
            className="rounded-sm bg-olive px-4 py-2 text-sm font-medium tracking-wide text-white transition hover:bg-olive-deep disabled:opacity-50"
          >
            {/* The button says what pressing it DOES, in the proposing tool's
                own words, for the same reason the sentence above the diff comes
                from the tool: this component renders every tool's proposals and
                cannot know. "Confirm" is right for the four that write to the
                reader's records and wrong for the one that does not — over a
                card naming a security it reads as approval of a purchase
                nobody proposed. */}
            {block.verb || "Confirm"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide("reject")}
            className="rounded-sm px-3 py-2 text-sm text-ink-soft transition hover:text-ink disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

// Three questions the chat can answer from the records alone, so the empty
// panel teaches what it is for instead of waiting to be guessed at.
const OPENERS = [
  "How am I doing against my goals?",
  "Which positions have a cost I never recorded?",
  "Run the analyzer and tell me what it says.",
];

function EndNote({ m }: { m: Message }) {
  switch (m.status) {
    case "done":
      return m.model ? <p className="mt-2 text-[0.7rem] text-ink-faint">{m.model}</p> : null;
    case "error":
      return <p className="mt-2 text-xs text-down">{m.detail ?? "The answer could not continue."}</p>;
    case "cut":
      return <p className="mt-2 text-xs text-down">Stopped before it was finished.</p>;
    case "aborted":
      return <p className="mt-2 text-xs text-ink-faint">Stopped.</p>;
    default:
      return null;
  }
}

/* An assistant turn, rendered IN ORDER. It used to be two joined strings —
   all the reasoning, then all the words — which was right while those were the
   only two kinds and stopped being right when something could happen in the
   middle. A tool consulted between two paragraphs has to appear between them:
   the words above it are what led to it and the words below are what it was
   for, and folding all the text into one block would file the call after a
   paragraph it interrupted. */
function Bubble({
  m,
  busy,
  onDecide,
  onOpenRun,
}: {
  m: Message;
  busy: boolean;
  onDecide: (cardId: string, decision: "confirm" | "reject") => void;
  onOpenRun: (runId: number) => void;
}) {
  if (m.role === "user") {
    // Where the question was asked, as the server stored it and the model was
    // told. Printed because it is an input to the answer the reader cannot
    // otherwise see: when the chat takes "this" to be the wrong thing, this
    // line is where they find out why.
    const where = m.blocks.find((b): b is ChatPageBlock => b.kind === "page");
    return (
      <div className="ml-8">
        <div className="whitespace-pre-wrap rounded-sm bg-olive-tint px-3 py-2 text-sm text-ink">
          {textOf(m)}
        </div>
        {where && (
          <p
            className="mt-1 text-right text-xs text-ink-faint"
            title="The page you were on when you asked: what the chat was told 'this' and 'here' point at"
          >
            asked on {where.label}
          </p>
        )}
      </div>
    );
  }
  const streaming = m.status === "streaming";
  return (
    <div className="mr-4 text-sm leading-relaxed text-ink">
      {/* Above the blocks, because it happened before them: the reader
          confirmed a card, the work ran, and only then was the model asked to
          say anything about it. */}
      {m.steps && m.steps.length > 0 && <Steps steps={m.steps} running={streaming} />}
      {m.blocks.map((b, i) => {
        // The last block of a turn that is still streaming is the one still
        // happening — which is how a running tool and a thought nothing has
        // answered yet are told from finished ones, with no extra state to
        // keep in step.
        const live = streaming && i === m.blocks.length - 1;
        if (b.kind === "thought") {
          return <Thought key={i} text={b.text} thinking={streaming} answered={!live} />;
        }
        if (b.kind === "tool") {
          return <ToolNote key={i} block={b} running={live} />;
        }
        if (b.kind === "sources") {
          return <Sources key={i} block={b} />;
        }
        // Where a question was asked belongs to the question. An answer never
        // carries one, and this line is what keeps a page from ever being fed
        // to the markdown renderer below as if it were words.
        if (b.kind === "page") return null;
        if (b.kind === "card") {
          return (
            <Card
              key={b.card_id}
              block={b}
              busy={busy}
              onDecide={(decision) => onDecide(b.card_id, decision)}
              onOpenRun={onOpenRun}
            />
          );
        }
        return (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={mdComponents}>
            {b.text}
          </ReactMarkdown>
        );
      })}
      {streaming && m.blocks.length === 0 && !m.steps?.length && (
        // Nothing has arrived yet, not even a thought: something is happening.
        <Spinner className="text-ink-soft" />
      )}
      <EndNote m={m} />
    </div>
  );
}

/* Small outline glyphs, drawn inline like the mark: no icon font, they inherit
   the ink, and they stay hairline-thin like the rest of the chrome. */
function ClockIcon() {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
      <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 6v4.5l3 1.8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M10 4v12M4 10h12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function ArrowUpIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M10 16V4M5 9l5-5 5 5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true" focusable="false">
      <rect x="4" y="4" width="12" height="12" rx="1.5" fill="currentColor" />
    </svg>
  );
}

export default function ChatPanel({
  open,
  page,
  onOpenRun,
  onOpenAnalyses,
}: {
  open: boolean;
  /** Where the reader is right now. Sent with each question at the moment it
      is sent, so a conversation that follows them across pages keeps, per
      question, where that question was asked. */
  page: ChatPage;
  /** Send the reader to one analysis run, in the main column. The panel does
      not render it: a verdict is a document and this is a narrow column, which
      is the argument that kept the chain on a page and does not disappear with
      the page. */
  onOpenRun: (runId: number) => void;
  /** Send the reader to the record of every run, also in the main column. */
  onOpenAnalyses: () => void;
}) {
  const [initial] = useState(load);
  const [conversationId, setConversationId] = useState<number | null>(initial.conversationId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [model, setModel] = useState<string | null>(initial.model);
  const [models, setModels] = useState<ChatModels | null>(null);
  const [draft, setDraft] = useState("");
  const [view, setView] = useState<"chat" | "history">("chat");
  const [history, setHistory] = useState<ChatConversation[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  /* The transcript's own scrollport, and whether it should be following the
     answer. Both are refs: the rule decides on every scroll event — measured
     at 48 of them from one wheel gesture — and re-rendering the panel that
     often to store a boolean would be paying for nothing. See
     `followStream.ts` for why the rule reads direction rather than distance,
     and why a fold is not a gesture. */
  const paneRef = useRef<HTMLDivElement | null>(null);
  const followRef = useRef<Follow>(FOLLOWING);
  const streaming = messages.some((m) => m.status === "streaming");

  function paneNow(): Pane | null {
    const el = paneRef.current;
    if (!el) return null;
    return {
      top: Math.round(el.scrollTop),
      height: el.scrollHeight,
      client: el.clientHeight,
    };
  }

  useEffect(() => {
    getChatModels()
      .then(setModels)
      .catch(() => {
        /* backend down: the dropdown shows nothing to pick, and the send will
           say the backend did not answer */
      });
  }, []);

  // A reload lands on the conversation that was open. If it is gone —
  // deleted from another tab, a fresh database — start blank rather than
  // show an error for something the reader did not do.
  useEffect(() => {
    if (initial.conversationId === null) return;
    getConversation(initial.conversationId)
      .then((c) => setMessages(c.messages.map(fromStored)))
      .catch(() => setConversationId(null));
  }, [initial.conversationId]);

  useEffect(() => {
    save({ conversationId, model });
  }, [conversationId, model]);

  /* Follow the answer down, by moving the TRANSCRIPT and nothing else.

     This used to be `bottomRef.current?.scrollIntoView({ block: "end" })`, and
     `scrollIntoView` scrolls every scrollable ancestor — the window included.
     Measured: the page behind the panel came back to exactly 0 on every
     attempt to scroll it during a stream, 3 of 3, and did the same with the
     panel CLOSED, because the panel stays mounted and the effect kept firing.
     Neutralising that one call mid-stream took all three symptoms the reader
     reported to 0 of 3 without changing anything else. Writing `scrollTop`
     cannot move the window, so the page is simply no longer involved. */
  useEffect(() => {
    const el = paneRef.current;
    const now = paneNow();
    if (!el || !now) return;
    const { state, scrollTo } = onContent(followRef.current, now);
    followRef.current = state;
    if (scrollTo !== null) el.scrollTop = scrollTo;
  }, [messages]);

  // Leaving the page while an answer streams: close the connection, so the
  // model on the far side stops too.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Grow the last block when the piece is of its kind, else start a new one:
  // one thought block, then one text block, not one block per token.
  function append(id: string, kind: "thought" | "text", text: string) {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== id) return m;
        const last = m.blocks[m.blocks.length - 1];
        const blocks: ChatBlock[] =
          last && last.kind === kind
            ? [...m.blocks.slice(0, -1), { kind, text: last.text + text }]
            : [...m.blocks, { kind, text }];
        return { ...m, blocks };
      }),
    );
  }

  /* A tool arrives WHOLE, so it cannot go through `append` — that function
     grows the last block by concatenating text, and a tool has none. `ok` is
     true here because no failure has been reported, not because a success
     has: a failure's reason travels with the event (since brief AG), and its
     absence claims nothing. See ToolNote. */
  function addTool(id: string, name: string, detail: string | null) {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id
          ? { ...m, blocks: [...m.blocks, { kind: "tool", name, ok: detail === null, detail }] }
          : m,
      ),
    );
  }

  // A page a web search found, onto the list it belongs to, by the rule the
  // server stores it with: a live answer and the same answer read back from
  // the history list the same pages in the same places.
  function addSource(id: string, page: WebPage) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, blocks: withSource(m.blocks, page) } : m)),
    );
  }

  // The page a question was stored as asked from, put in front of its words the
  // way the server stores it — so a question on screen and the same question
  // reloaded from the history look the same.
  function addPage(id: string, label: string) {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id ? { ...m, blocks: [{ kind: "page", label }, ...m.blocks] } : m,
      ),
    );
  }

  // A card arrives whole too, and it is the last thing a turn sends: the model
  // proposed a write and stopped.
  function addCard(id: string, card: ChatCardBlock) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, blocks: [...m.blocks, card] } : m)),
    );
  }

  // A finished step of a long tool. Appended to its own list rather than to
  // `blocks`, because `blocks` is what the server stores and these are not
  // stored: what they narrate has a record of its own.
  function addStep(id: string, step: ChatStepEvent) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, steps: [...(m.steps ?? []), step] } : m)),
    );
  }

  async function send(question: string) {
    const q = question.trim();
    if (!q || streaming) return;
    // Whatever they were reading, they are here now and waiting for an
    // answer. Without this, one scroll up during one answer would silently
    // stop every answer for the rest of the session.
    followRef.current = onSend(followRef.current);
    const user = newMessage("user", [{ kind: "text", text: q }]);
    const answer = newMessage("assistant", [], "streaming");
    setMessages((prev) => [...prev, user, answer]);
    setDraft("");
    setView("chat");

    const controller = new AbortController();
    abortRef.current = controller;
    const end = await streamChat(
      { conversation_id: conversationId, content: q, model, page },
      {
        onStart: (cid, _question, pageLabel) => {
          setConversationId(cid);
          if (pageLabel) addPage(user.id, pageLabel);
        },
        onThought: (text) => append(answer.id, "thought", text),
        onDelta: (text) => append(answer.id, "text", text),
        onTool: (name, detail) => addTool(answer.id, name, detail),
        onSource: (found) => addSource(answer.id, found),
        onStep: (step) => addStep(answer.id, step),
        onCard: (card) => addCard(answer.id, card),
        // A question never decides a card; the handler is here because the
        // stream's handlers are one type for both endpoints.
        onDecided: (card) => setMessages((prev) => withDecided(prev, card)),
      },
      controller.signal,
    );
    abortRef.current = null;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === answer.id
          ? {
              ...m,
              status: end.kind,
              detail: end.kind === "error" ? end.detail : undefined,
              model: end.kind === "done" ? end.model : undefined,
            }
          : m,
      ),
    );
  }

  /* Answering a card. The write has already happened by the time the first
     byte arrives — the endpoint runs it before it starts streaming — so a
     stream that starts at all is a decision taken, and the truth about the
     card is on the server rather than here. So the card is never coloured in
     from a guess of this panel's: it is replaced by the card the server sends
     as stored, `decided`, which arrives right after `start` (after the steps,
     for the analyzer), before the reply and whatever becomes of it. `result`
     is what the write produced, and only the server knows it.

     And whatever the ending, the conversation is read back from the server
     afterwards, as a finished one always was: a reply that failed is stored
     with its sentence, and a card decided in another window shows its state.
     Until brief AJ this read happened only on `done`, so a reply that failed
     left a decided card with its buttons, and pressing one again was refused
     as a decision already taken (the reader, 2026-10-08).

     A refusal (the card is gone, already answered, or stale) never starts a
     stream and is stored nowhere, so it stays on screen under the
     conversation as read, with any card still pending still answerable. */
  async function decide(cardId: string, decision: "confirm" | "reject") {
    if (streaming) return;
    const answer = newMessage("assistant", [], "streaming");
    setMessages((prev) => [...prev, answer]);

    const controller = new AbortController();
    abortRef.current = controller;
    let started = false;
    const end = await decideCard(
      cardId,
      { decision, model },
      {
        onStart: (cid) => {
          started = true;
          setConversationId(cid);
        },
        onDecided: (card) => setMessages((prev) => withDecided(prev, card)),
        onThought: (text) => append(answer.id, "thought", text),
        onDelta: (text) => append(answer.id, "text", text),
        onTool: (name, detail) => addTool(answer.id, name, detail),
        onSource: (found) => addSource(answer.id, found),
        onStep: (step) => addStep(answer.id, step),
        onCard: (card) => addCard(answer.id, card),
      },
      controller.signal,
    );
    abortRef.current = null;

    const ended: Message = {
      ...answer,
      status: end.kind,
      detail: end.kind === "error" ? end.detail : undefined,
      model: end.kind === "done" ? end.model : undefined,
    };
    if (conversationId !== null) {
      try {
        const full = await getConversation(conversationId);
        const stored = full.messages.map(fromStored);
        setMessages(started ? stored : [...stored, ended]);
        return;
      } catch {
        /* the backend did not answer: keep what is on screen, ended */
      }
    }
    setMessages((prev) => prev.map((m) => (m.id === answer.id ? { ...m, ...ended, blocks: m.blocks } : m)));
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a new line, as in every chat the reader knows.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(draft);
    }
  }

  // A new conversation is only a blank panel: the record opens on the server
  // with the first question, so "New" pressed twice does not litter the
  // history with empty rows.
  function startNew() {
    abortRef.current?.abort();
    setConversationId(null);
    setMessages([]);
    setView("chat");
  }

  function openHistory() {
    setView("history");
    setHistoryError(null);
    listConversations()
      .then(setHistory)
      .catch((e) => setHistoryError(apiError(e, "The history could not be loaded.")));
  }

  async function resume(c: ChatConversation) {
    abortRef.current?.abort();
    try {
      const full = await getConversation(c.id);
      setConversationId(c.id);
      setMessages(full.messages.map(fromStored));
      setView("chat");
    } catch (e) {
      setHistoryError(apiError(e, "That conversation could not be loaded."));
    }
  }

  async function forget(c: ChatConversation) {
    try {
      await deleteConversation(c.id);
      setHistory((prev) => prev?.filter((x) => x.id !== c.id) ?? null);
      if (c.id === conversationId) {
        setConversationId(null);
        setMessages([]);
      }
    } catch (e) {
      setHistoryError(apiError(e, "That conversation could not be deleted."));
    }
  }

  const currentModel = model ?? models?.default ?? "";
  const currentNote = models?.models.find((m) => m.slug === currentModel)?.note ?? undefined;

  // The width is written once and applied to BOTH the animated outer shell and
  // the inner column, so while the shell slides the text inside is revealed
  // rather than reflowed. The page beside it does reflow, deliberately
  // animated over 300ms so the eye can follow the tables moving; the tables
  // themselves scroll horizontally inside their cards rather than squeezing.
  const width = "w-[32vw] min-w-[280px] max-w-[35vw]";

  return (
    // The aside ITSELF is the sticky element, one viewport tall, so it follows
    // the reader down a long page like the rail does. It cannot be a sticky
    // child inside an overflow-hidden shell: the shell is needed to clip the
    // width animation, and an overflow ancestor is what a sticky child sticks
    // to — it would ride away with the page, which is what happened.
    <aside
      aria-label="Chat with Aurelio"
      aria-hidden={!open}
      className={
        "sticky top-0 h-screen shrink-0 self-start overflow-hidden border-r border-rule bg-surface transition-[width] duration-300 ease-in-out motion-reduce:transition-none " +
        (open ? width : "w-0 border-r-0")
      }
    >
      <div className={"flex h-full flex-col " + width}>
        {/* No mark here: the one in the header is enough, and the rail's
            button is the panel's only open/close control. */}
        <div className="flex items-center gap-2 border-b border-rule px-4 py-3">
          <span className="font-display text-lg leading-none text-ink">Ask Aurelio</span>
          <button
            type="button"
            onClick={view === "history" ? () => setView("chat") : openHistory}
            aria-label={view === "history" ? "Back to the conversation" : "Past conversations"}
            aria-pressed={view === "history"}
            title={view === "history" ? "Back to the conversation" : "Past conversations"}
            className={
              "ml-auto rounded-sm p-1.5 transition " +
              (view === "history"
                ? "bg-olive-tint text-olive-deep"
                : "text-ink-soft hover:bg-tint hover:text-ink")
            }
          >
            <ClockIcon />
          </button>
        </div>

        {view === "history" ? (
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {/* Two kinds of "before" belong to this panel, and only one of them
                is a conversation. An analysis is a document the chat ORDERED:
                it outlives the talk around it, deleting the conversation does
                not delete the run, and the card that pointed at it scrolls
                away. So the way back to a run cannot be the card, and it is
                here, beside the other history rather than behind a tab of its
                own. It opens in the main column, at the width prose is read
                at. */}
            <button
              type="button"
              onClick={onOpenAnalyses}
              className="-mx-2 mb-4 flex w-[calc(100%+1rem)] cursor-pointer items-center gap-2 rounded-sm px-2 py-2 text-left text-sm text-olive transition hover:bg-tint"
            >
              Past analyses
              <span aria-hidden="true" className="ml-auto text-ink-faint">
                ›
              </span>
            </button>
            <p className="mb-3 text-[0.65rem] font-medium uppercase tracking-[0.14em] text-ink-soft">
              Past conversations
            </p>
            {historyError && <p className="text-sm text-down">{historyError}</p>}
            {history === null && !historyError && <p className="text-sm text-ink-soft">Loading…</p>}
            {history !== null && history.length === 0 && (
              <p className="text-sm text-ink-soft">Nothing yet. Ask something and it will be kept here.</p>
            )}
            {/* Each row is a button and has to look like one: a pointer, a
                hover ground, a chevron — the same grammar as the list rows in
                Records. The open conversation is inked and marked. */}
            {history !== null && history.length > 0 && (
              <ul className="-mx-2 space-y-0.5">
                {history.map((c) => (
                  <li key={c.id} className="flex items-center rounded-sm transition hover:bg-tint">
                    <button
                      type="button"
                      onClick={() => void resume(c)}
                      className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 px-2 py-2.5 text-left"
                    >
                      <span
                        aria-hidden="true"
                        className={
                          "h-1.5 w-1.5 shrink-0 rounded-full " +
                          (c.id === conversationId ? "bg-olive" : "bg-transparent")
                        }
                      />
                      <span className="min-w-0 flex-1">
                        <span
                          className={
                            "block truncate text-sm " +
                            (c.id === conversationId ? "font-medium text-ink" : "text-ink")
                          }
                        >
                          {c.title ?? "Untitled"}
                        </span>
                        <span className="block text-[0.7rem] text-ink-faint">
                          {new Date(c.updated_at).toLocaleString(locale)}
                        </span>
                      </span>
                      <span aria-hidden="true" className="text-ink-faint">
                        ›
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void forget(c)}
                      aria-label="Delete this conversation"
                      title="Delete this conversation"
                      className="shrink-0 cursor-pointer px-2 py-2 text-ink-faint transition hover:text-down"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div
            ref={paneRef}
            /* Every scroll of this pane is either the reader's hand, the clamp
               after `Thought` folds itself, or our own write echoing back.
               `followStream.onScroll` tells them apart; nothing here needs to
               know which. */
            onScroll={() => {
              const now = paneNow();
              if (now) followRef.current = onScroll(followRef.current, now);
            }}
            className="flex-1 space-y-4 overflow-y-auto px-4 py-4"
          >
            {messages.length === 0 ? (
              // Three ways in, sitting a little below the middle of the empty
              // panel — where the eye rests, not where a heading would go.
              <div className="flex h-full flex-col justify-center pt-[14%]">
                <ul className="space-y-2">
                  {OPENERS.map((q) => (
                    <li key={q}>
                      <button
                        type="button"
                        onClick={() => void send(q)}
                        className="cursor-pointer text-left text-sm text-olive underline-offset-2 hover:underline"
                      >
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              messages.map((m) => (
                <Bubble
                  key={m.id}
                  m={m}
                  busy={streaming}
                  onDecide={decide}
                  onOpenRun={onOpenRun}
                />
              ))
            )}
          </div>
        )}

        {/* The composer is one card: the question on top, the controls in a
            quiet row inside the same border — new conversation on the left,
            the model as a pill, the send arrow on the right. One object to
            look at, not a field with loose buttons under it. */}
        <form onSubmit={onSubmit} className="px-4 pb-4 pt-2">
          <div className="rounded-sm border border-rule bg-surface transition focus-within:border-olive focus-within:ring-1 focus-within:ring-olive">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              rows={2}
              placeholder="Ask about your finances…"
              aria-label="Your question"
              className="block w-full resize-none bg-transparent px-3 pt-3 pb-1 text-sm outline-none placeholder:text-ink-faint"
            />
            <div className="flex items-center gap-2 px-2 pb-2">
              <button
                type="button"
                onClick={startNew}
                disabled={messages.length === 0}
                aria-label="New conversation"
                title="New conversation"
                className="rounded-sm p-1.5 text-ink-soft transition hover:bg-tint hover:text-ink disabled:opacity-40 disabled:hover:bg-transparent"
              >
                <PlusIcon />
              </button>
              {/* The model is chosen, not assumed. Default first; the title
                  says what is known about the current one and when. */}
              <select
                value={currentModel}
                onChange={(e) => setModel(e.target.value || null)}
                disabled={!models}
                aria-label="Model"
                title={currentNote}
                className="min-w-0 max-w-[60%] truncate rounded-full border border-hair bg-transparent px-2.5 py-1 text-xs text-ink-soft outline-none transition hover:border-rule hover:text-ink focus:border-olive"
              >
                {models ? (
                  models.models.map((m) => (
                    <option key={m.slug} value={m.slug}>
                      {m.slug.includes("/") ? m.slug.slice(m.slug.indexOf("/") + 1) : m.slug}
                      {m.slug === models.default ? " · default" : ""}
                    </option>
                  ))
                ) : (
                  <option value="">model…</option>
                )}
              </select>
              {streaming ? (
                <button
                  type="button"
                  onClick={() => abortRef.current?.abort()}
                  aria-label="Stop the answer"
                  title="Stop the answer"
                  className="ml-auto flex h-8 w-8 items-center justify-center rounded-full bg-ink text-ground transition hover:bg-ink-soft"
                >
                  <StopIcon />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!draft.trim()}
                  aria-label="Send"
                  title="Send (Enter)"
                  className="ml-auto flex h-8 w-8 items-center justify-center rounded-full bg-olive text-white transition hover:bg-olive-deep disabled:opacity-40 disabled:hover:bg-olive"
                >
                  <ArrowUpIcon />
                </button>
              )}
            </div>
          </div>
          <p className="mt-2 text-center text-[0.65rem] leading-snug text-ink-faint">
            Educational information, not regulated financial advice.
          </p>
        </form>
      </div>
    </aside>
  );
}
