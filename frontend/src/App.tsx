import { useEffect, useState, type ReactNode } from "react";
import type { ChatPage } from "./api/chat";
import type { Institution } from "./api/institutions";
import type { Liability } from "./api/liabilities";
import type { RealAsset } from "./api/realAssets";
import type { Snapshot } from "./api/snapshots";
import { getBaseCurrency } from "./api/baseCurrency";
import { ensureCatalogue } from "./api/instruments";
import { catchUp, type CatchUpResult } from "./api/transactions";
import Dashboard from "./components/Dashboard";
import Portfolio from "./components/Portfolio";
import Records, { type RecordsPage } from "./components/Records";
import Profile from "./components/Profile";
import Goals from "./components/Goals";
import Analysis from "./components/Analysis";
import ChatPanel from "./components/ChatPanel";
import { Mark } from "./components/Emblem";
import { CURRENCY_LIST } from "./components/ui";
import { dividendsNote } from "./components/catchUpNote";
import type { Focus } from "./nav";

// Four voices, grouped by what you are DOING rather than by database table:
// read the overview, read the investments, enter records, describe yourself.
//
// Asking the models was the fifth, and it is not a tab any more. The analyzer
// is something you ASK FOR — a card in the chat that says what a minute and a
// few cents buy, confirmed, then watched step by step — and a tab called
// Analyzer with nothing on it but a button was the page that made the wait
// silent. What the page WAS for survives: a verdict is a document, so reading
// one still happens here in the main column, opened from the card that
// produced it. See `reading` below.
const TABS = [
  { key: "dashboard", label: "Dashboard", wide: true },
  { key: "portfolio", label: "Portfolio", wide: true },
  { key: "records", label: "Records", wide: true },
  { key: "profile", label: "Profile", wide: false },
] as const;

// Two measures, not one. 1024px is a READING measure — it exists to hold a line
// under about 75 characters — but a table is not read, it is scanned, and at
// that width the Portfolio's eight columns get roughly 120px each, inside which
// "P/L vs recorded" has to fit two numbers and a note. Data views get 1280;
// prose stays at 1024, because the models' reports ARE prose and widening them
// makes them more tiring, not less.
//
// Neither fills the screen. Past ~1600px a cell drifts so far from its heading
// that the eye loses the row — the opposite defect, and the worse one.
const READING = "max-w-5xl";
const SCANNING = "max-w-7xl";

type Tab = (typeof TABS)[number]["key"];

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  // Editorial nav: no pills. The active tab is inked and underscored by the
  // accent rule; the rest recede.
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={
        "border-b-2 px-1.5 py-1 text-sm transition " +
        (active
          ? "border-olive font-semibold text-ink"
          : "border-transparent text-ink-soft hover:text-ink")
      }
    >
      {children}
    </button>
  );
}

// The rail: a narrow column on the far left that is always there, and IS the
// button — the whole strip opens and closes the chat, not a glyph inside it.
// It has to be read as the chat before it is pressed, so it carries a tinted
// ground, the speech bubble, and its name spelled out down its length; the
// panel slides out from behind it, so the control sits where the thing it
// controls comes from.
function ChatRail({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-label={open ? "Close the chat" : "Open the chat"}
      aria-pressed={open}
      title={open ? "Close the chat" : "Ask Aurelio about your finances"}
      className={
        "relative sticky top-0 z-10 flex h-screen w-14 shrink-0 items-center justify-center border-r transition " +
        (open
          ? "border-olive-deep bg-olive text-white hover:bg-olive-deep"
          : "border-rule bg-olive-tint text-olive-deep hover:bg-olive hover:text-white")
      }
    >
      <span className="absolute top-5" aria-hidden="true">
        {open ? (
          // A chevron pointing back at the rail: press to fold the panel away.
          <svg viewBox="0 0 24 24" width="26" height="26" focusable="false">
            <path
              d="M14.5 6 8.5 12l6 6"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : (
          // A speech bubble with the three dots of an answer being written.
          <svg viewBox="0 0 24 24" width="26" height="26" focusable="false">
            <path
              d="M4 5.5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-9.5L6 20.5v-4H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <circle cx="8.5" cy="11" r="1.1" fill="currentColor" />
            <circle cx="12" cy="11" r="1.1" fill="currentColor" />
            <circle cx="15.5" cy="11" r="1.1" fill="currentColor" />
          </svg>
        )}
      </span>
      {/* Spelled out at the centre of the strip, reading upward the way a
          book's spine does, in the display face so it is a name and not a label. */}
      <span
        aria-hidden="true"
        className="font-display text-xl leading-none tracking-wide [writing-mode:vertical-rl] rotate-180"
      >
        {open ? "Close the chat" : "Ask Aurelio"}
      </span>
    </button>
  );
}

// Banner shown when the ledger catch-up created (or failed to create) entries.
function PacBanner({
  result,
  onDismiss,
  onOpenPortfolio,
  measure,
}: {
  result: CatchUpResult;
  onDismiss: () => void;
  onOpenPortfolio: () => void;
  measure: string;
}) {
  const buys = result.created.filter((t) => t.kind === "buy").length;
  const divs = result.created.filter((t) => t.kind === "dividend").length;
  const parts = [
    buys > 0 ? `${buys} PAC purchase${buys > 1 ? "s" : ""}` : null,
    divs > 0 ? `${divs} dividend${divs > 1 ? "s" : ""}` : null,
  ].filter(Boolean);
  return (
    <div className="border-b border-olive-tint bg-olive-tint">
      <div
        className={
          "mx-auto flex flex-wrap items-center gap-x-3 gap-y-1 px-6 py-2.5 text-sm text-olive-deep " +
          measure
        }
      >
        {parts.length > 0 && (
          <span>
            <span className="font-semibold">{parts.join(" and ")}</span> recorded automatically
            (marked <em>estimated</em>: correct them with the real amounts if they differ).{" "}
            {divs > 0 && <>{dividendsNote(divs)} </>}
            <button onClick={onOpenPortfolio} className="font-medium underline">
              Review in Portfolio
            </button>
          </span>
        )}
        {result.skipped.length > 0 && (
          <span className="text-olive-deep">
            {result.skipped.length} occurrence{result.skipped.length > 1 ? "s" : ""} skipped
            ({result.skipped[0].reason}
            {result.skipped.length > 1 ? ", …" : ""}). Will retry at next start.
          </span>
        )}
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="ml-auto px-2 text-olive hover:text-olive-deep"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export default function App() {
  // The dashboard is the landing view: you read it far more often than you
  // fill in your profile.
  const [tab, setTab] = useState<Tab>("dashboard");
  const [pacResult, setPacResult] = useState<CatchUpResult | null>(null);
  /* The codes the rate feed quotes, offered to every currency box in the app
     (`CURRENCY_LIST`). Fetched once here rather than per form: `<datalist>` is
     referenced by document id, so one element serves inputs anywhere in the
     tree, and a page with four currency boxes does not ask four times. */
  const [quoted, setQuoted] = useState<string[]>([]);
  // The chat panel: state ABOVE the tabs, because a conversation that forgot
  // itself when you went to look at the table it was talking about would be a
  // tab in disguise. It stays as you left it when you navigate — open follows
  // you, closed frees the page — and the panel keeps its own history.
  //
  // And it knows where you are: every question is sent with `page`, below,
  // which is the other half of moving around with the chat open. Its context
  // is still the whole picture; the page only says what
  // "this" points at, and it is sent per question because you move between
  // questions.
  const [chatOpen, setChatOpen] = useState(false);
  // Which analysis run is open in the main column, "list" for the record of
  // all of them, or null for the tab. Not a tab of its own, because you do not
  // GO to an analysis: a card in the chat sends you to the one it produced, and
  // the tabs stay where they are so leaving is the same gesture it always was.
  //
  // "list" exists because a receipt is a poor last resort. A run outlives the
  // conversation that ordered it — deleting the chat deletes no record — so
  // there has to be a way to the runs that does not depend on a card still
  // being on screen. It is reached from the panel's history, beside the other
  // kind of "before".
  const [reading, setReading] = useState<number | "list" | null>(null);

  // Which page of Records is open, and which section a link asked us to scroll
  // to when we get there. Both live up here for the same reason: the account
  // page prints a sentence about six quantities and is the sole home of one of
  // them, so the other five have to be able to say where they are kept — and
  // "Records → Cash flow, at Income" is two facts, one of which used to be
  // locked inside Records.
  const [recordsPage, setRecordsPage] = useState<RecordsPage>("wealth");
  const [focus, setFocus] = useState<Focus | null>(null);

  // Which account and which situation Wealth has open. Up here and not inside
  // Wealth, where they used to be, because a question can be about exactly
  // them — "why is this so low?" on an account's page is about that account — and a
  // page App cannot see is a page the chat cannot be told about.
  const [account, setAccount] = useState<Institution | null>(null);
  const [situation, setSituation] = useState<Snapshot | null>(null);
  // The same for the real asset and the debt open on their pages.
  const [realAsset, setRealAsset] = useState<RealAsset | null>(null);
  const [debt, setDebt] = useState<Liability | null>(null);

  // Where the reader is, at the level a question can be about: the object the
  // page is titled after, never a row inside it. Read at the moment a
  // question is sent, so each question carries its own. The server turns the
  // ids into names, and answers for the level above one that is gone.
  let page: ChatPage;
  if (reading === "list") page = { kind: "analyses" };
  else if (reading !== null) page = { kind: "analysis", run_id: reading };
  else if (tab === "records" && recordsPage === "wealth" && account !== null)
    page =
      situation !== null
        ? { kind: "situation", institution_id: account.id, snapshot_id: situation.id }
        : { kind: "account", institution_id: account.id };
  else if (tab === "records" && recordsPage === "real" && realAsset !== null)
    page = { kind: "real_asset", real_asset_id: realAsset.id };
  else if (tab === "records" && recordsPage === "debts" && debt !== null)
    page = { kind: "debt", liability_id: debt.id };
  else if (tab === "records") page = { kind: "records", section: recordsPage };
  else page = { kind: tab };

  // A term in that sentence, pressed. The tab moves, the sub-page moves with
  // it where it needs to, and the section says so on arrival by scrolling to
  // itself. It does NOT filter what it lands on: every one of these lists
  // already prints the institution on every row, so the reader who came from
  // an account can see which rows are its own without the page hiding the rest
  // — and a filter left switched on would quietly hide the eleventh expense
  // from someone entering ten in a row, which is the workflow the account page
  // exists alongside rather than replaces.
  function go(f: Focus) {
    setReading(null);
    if (f === "ledger") {
      setTab("portfolio");
    } else {
      setTab("records");
      setRecordsPage("cash");
    }
    setFocus(f);
  }

  // The header follows the page rather than staying fixed, so the mark always
  // sits directly above the content's left edge instead of floating over a
  // margin on the reading pages.
  //
  // Centred only while the chat is closed. Beside an open panel the leftover
  // column is narrower and the reading measure floated inside it, so Analyzer
  // and Profile started 120px to the right of Portfolio and the header jumped
  // between tabs. Open, every page shares one left edge, right after the panel.
  // An analysis is prose, so it is read at the reading measure whatever tab it
  // was opened from.
  const measure =
    (chatOpen ? "" : "mx-auto ") +
    (reading === null && TABS.find((t) => t.key === tab)?.wide ? SCANNING : READING);

  // Ledger catch-up at app start: elapsed PAC occurrences become Buys, and
  // dividend ex-dates of dist positions become dividend entries (idempotent —
  // nothing happens twice). No timer needed: dates are reconstructed
  // retroactively even after months away.
  // What the feed quotes, for the suggestion list on every currency box. A
  // failure is not worth saying: the boxes go on taking a typed code, which is
  // what they did before there was a list.
  useEffect(() => {
    getBaseCurrency()
      .then((b) => setQuoted(b.available))
      .catch(() => {});
  }, []);

  useEffect(() => {
    catchUp()
      .then((r) => {
        if (r.created.length > 0 || r.skipped.length > 0) setPacResult(r);
      })
      .catch(() => {
        /* backend down: the next start retries */
      });
  }, []);

  // The fund catalogue, which the forms' instrument search and the chat both
  // read. Nobody presses anything for it: every page load asks, like the
  // catch-up, and the backend decides. It downloads in the background only
  // when the catalogue is missing or a week old, one download at a time, and
  // answers at once, so nothing here waits for justETF.
  useEffect(() => {
    ensureCatalogue().catch(() => {
      /* backend down: the next page load asks again */
    });
  }, []);

  return (
    // Panel and page side by side. The page column is `min-w-0` so the tables
    // inside it can scroll horizontally in their own cards instead of forcing
    // the column wider; the panel animates its width so what moves, moves
    // where the eye can follow it.
    <div className="flex min-h-screen bg-ground text-ink">
      {/* Suggestions, not a choice. A closed dropdown of the feed's codes would
          answer the matching question and refuse a real holding: the ECB does
          not quote TWD, and a Taipei-listed fund is an ordinary thing to own —
          nor GBp, which London genuinely quotes in pence. So the boxes stay
          typeable, the shape is checked on the way in (`StatedCurrency`), and
          an amount nobody can convert is named beside the total it entered
          (`UnconvertedNotice`). This is the part that answers "how do they
          match with the rest?". */}
      <datalist id={CURRENCY_LIST}>
        {quoted.map((code) => (
          <option key={code} value={code} />
        ))}
      </datalist>
      <ChatRail open={chatOpen} onToggle={() => setChatOpen((o) => !o)} />
      <ChatPanel
        open={chatOpen}
        page={page}
        onOpenRun={setReading}
        onOpenAnalyses={() => setReading("list")}
      />
      <div className="min-w-0 flex-1">
        {pacResult && (
          <PacBanner
            result={pacResult}
            onDismiss={() => setPacResult(null)}
            onOpenPortfolio={() => {
              setReading(null);
              setTab("portfolio");
            }}
            measure={measure}
          />
        )}
        <header className="border-b border-rule bg-surface">
          <div
            className={"flex flex-wrap items-baseline gap-x-8 gap-y-2 px-6 py-4 " + measure}
          >
            {/* One ink, mark and name alike: beside the tinted rail a second
                accent on the mark was one colour too many. */}
            <span className="flex items-center gap-2.5 text-ink">
              <Mark size={26} accent="currentColor" />
              <span className="font-display text-2xl leading-none tracking-wide text-ink">
                Aurelio
              </span>
            </span>
            <nav className="flex flex-wrap gap-x-4 gap-y-1">
              {TABS.map((t) => (
                <TabButton
                  key={t.key}
                  active={reading === null && tab === t.key}
                  onClick={() => {
                    setReading(null);
                    setTab(t.key);
                  }}
                >
                  {t.label}
                </TabButton>
              ))}
            </nav>
          </div>
        </header>

        <main className={"px-6 py-8 " + measure}>
          {reading !== null ? (
            <Analysis
              runId={reading === "list" ? null : reading}
              onOpen={(id) => setReading(id ?? "list")}
              onClose={() => setReading(null)}
            />
          ) : (
            <>
              {tab === "dashboard" && <Dashboard />}
              {tab === "portfolio" && (
                <Portfolio
                  focus={focus === "ledger" ? "ledger" : null}
                  onFocused={() => setFocus(null)}
                />
              )}
              {tab === "records" && (
                <Records
                  page={recordsPage}
                  onPage={setRecordsPage}
                  focus={focus === "ledger" ? null : focus}
                  onFocused={() => setFocus(null)}
                  go={go}
                  account={account}
                  onAccount={setAccount}
                  situation={situation}
                  onSituation={setSituation}
                  realAsset={realAsset}
                  onRealAsset={setRealAsset}
                  debt={debt}
                  onDebt={setDebt}
                />
              )}
              {/* Profile and Goals are two halves of one answer — who you are,
                  and what you want measurably — so they share a page. */}
              {tab === "profile" && (
                <div className="space-y-12">
                  <Profile />
                  <Goals />
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
