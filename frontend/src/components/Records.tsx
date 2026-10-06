import Wealth from "./Wealth";
import RealAssets from "./RealAssets";
import Debts from "./Debts";
import CashFlow from "./CashFlow";
import type { Institution } from "../api/institutions";
import type { Liability } from "../api/liabilities";
import type { RealAsset } from "../api/realAssets";
import type { Snapshot } from "../api/snapshots";
import type { Focus } from "../nav";

/* Records groups everything you ENTER — institutions and dated situations,
   cash, real assets, debts, flows and plans — behind one top-level voice.
   The app used to expose one tab per database table; grouping by activity
   (entering vs reading) is what took the nav from nine voices to five. */

const PAGES = [
  {
    key: "wealth",
    label: "Wealth",
  },
  {
    key: "real",
    label: "Real assets",
  },
  {
    key: "debts",
    label: "Debts",
  },
  {
    key: "cash",
    label: "Cash flow",
  },
] as const;

export type RecordsPage = (typeof PAGES)[number]["key"];

/* The sub-page is a PROP, not local state. It used to be a `useState` in here,
   which made this the one nav in the app that nothing outside could drive: the
   cash register could name "Cash flow" as the home of its income figure and
   had no way to open it. Lifting it is the whole structural cost of turning
   that explanation into navigation.

   It follows that the sub-page now survives a trip to another top tab, where
   before it snapped back to Wealth on unmount. That is the better of the two:
   leaving Records to check the Dashboard and coming back to where you were
   typing is what the reader expects, and the old reset was an accident of
   where the state happened to live rather than a decision. */
export default function Records({
  page,
  onPage,
  focus,
  onFocused,
  go,
  account,
  onAccount,
  situation,
  onSituation,
  realAsset,
  onRealAsset,
  debt,
  onDebt,
}: {
  page: RecordsPage;
  onPage: (p: RecordsPage) => void;
  /** A section of Cash flow to scroll to on arrival, when the reader came here
      from the account page's sentence rather than by pressing "Cash flow". */
  focus: Focus | null;
  onFocused: () => void;
  go: (f: Focus) => void;
  /** Which account and which situation Wealth has open. App's state, for the
      reason the sub-page is: the chat is told where the reader is. */
  account: Institution | null;
  onAccount: (i: Institution | null) => void;
  situation: Snapshot | null;
  onSituation: (s: Snapshot | null) => void;
  /** The real asset and the debt open on their pages, for the same reason. */
  realAsset: RealAsset | null;
  onRealAsset: (a: RealAsset | null) => void;
  debt: Liability | null;
  onDebt: (l: Liability | null) => void;
}) {
  const current = PAGES.find((p) => p.key === page) ?? PAGES[0];

  return (
    <div className="space-y-6">
      <nav className="flex flex-wrap gap-x-5 gap-y-1 border-b border-rule pb-2">
        {PAGES.map((p) => (
          <button
            key={p.key}
            onClick={() => onPage(p.key)}
            aria-current={p.key === page ? "page" : undefined}
            className={
              "-mb-2 border-b-2 pb-2 text-sm transition " +
              (p.key === page
                ? "border-olive font-semibold text-ink"
                : "border-transparent text-ink-soft hover:text-ink")
            }
          >
            {p.label}
          </button>
        ))}
      </nav>
      {current.key === "wealth" && (
        <Wealth
          go={go}
          institution={account}
          onInstitution={onAccount}
          snapshot={situation}
          onSnapshot={onSituation}
        />
      )}
      {current.key === "real" && <RealAssets asset={realAsset} onAsset={onRealAsset} />}
      {current.key === "debts" && <Debts liability={debt} onLiability={onDebt} />}
      {current.key === "cash" && (
        <CashFlow
          focus={focus}
          onFocused={onFocused}
          onOpenAccount={(i) => {
            // The account's own page, not one of its situations: the one to
            // record today is started there.
            onSituation(null);
            onAccount(i);
            onPage("wealth");
          }}
        />
      )}
    </div>
  );
}
