import {
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type FormEvent,
  type Ref,
} from "react";
import { getPortfolio, type Portfolio as PortfolioData } from "../api/portfolio";
import type { TaxEstimate } from "../api/tax";
import {
  createTransaction,
  deleteTransaction,
  getTransactions,
  updateTransaction,
  type Transaction,
} from "../api/transactions";
import {
  getPortfolioComposition,
  type MatrixCell,
  type PortfolioComposition,
} from "../api/composition";
import {
  createInstitution,
  getInstitutions,
  type Institution,
} from "../api/institutions";
import { getAllCashAnchors, getCashPositions, type CashAnchor, type CashPosition } from "../api/cash";
import { EmptyState } from "./Emblem";
import { OmissionsNotice } from "./OmissionsNotice";
import { acrossCurrencies as isAcross, debitOnEdit, derivedAmount } from "./statedAmount";
import { UnconvertedNotice } from "./UnconvertedNotice";
import { getListingCurrencies, getQuote } from "../api/prices";
import { accountCurrencyOn, listingCurrencyOf } from "./proposedCurrency";
import { InstrumentPicker } from "./InstrumentPicker";
import Watchlist from "./Watchlist";
import { prefillNote } from "./watchItem";
import type { WatchlistItem } from "../api/watchlist";
import { Row, RowsOrEmpty, Section, apiError, btnClass, cardClass, inputClass, locale, money, todayISO, CURRENCY_LIST } from "./ui";
import { dividendWord } from "./dividendLine";
import { avgCostTitle, plTitle } from "./costWords";
import { marks, refusal, transaction } from "./required";
import type { Focus } from "../nav";

const pctFmt = new Intl.NumberFormat(locale, {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: "exceptZero",
});

function toneClass(delta: number | null): string {
  if (delta == null || delta === 0) return "text-ink-soft";
  return delta > 0 ? "text-up" : "text-down";
}

/* The declared tax estimate, BESIDE the totals and never inside one.

   That placement is the whole design. Nothing above this panel moved because a
   rate was set: not the market total, not the recorded total, not the net
   worth on the dashboard. A tax folded into a portfolio figure would make the
   app answer "what am I worth" with a number that depends on a percentage the
   reader typed into a form, and it would be wrong in a way no column could
   show. Here it sits next to the two figures it came from, wearing its rate.

   The panel is also the one place that distinguishes "nobody answered" from
   "there is nothing there". With no rate set it asks for one and names the
   bases waiting on it — a state that is NOT zero tax and must never look like
   it. */
function TaxEstimatePanel({ est, baseCurrency }: { est: TaxEstimate; baseCurrency: string }) {
  // The estimate travels inside the portfolio payload, in its base.
  const inBase = money(baseCurrency);
  /* A realized LOSS counts as something to say, even though it is not a base:
     "you sold at a loss and no tax is estimated on it" is the reader's answer,
     and going silent would leave them to assume the rate had been applied. */
  const hasBase =
    est.realized_gain !== 0 || est.dividends_gross_estimated > 0;
  /* No base, no panel — whether or not a rate is set. The rest of this header
     already works this way: the realized-P/L line hides itself when there is
     nothing realized, and a row reading "estimated tax 0.00" is the same noise
     wearing a heading. The advisor context does NOT follow this rule and still
     carries the declared rate with no base, because a model asked "what would
     I pay if I sold this" should quote the reader's own figure rather than
     reach for one of its own. A screen and a prompt want different silences. */
  if (!hasBase) return null;

  if (!est.configured) {
    return (
      <div className={cardClass + " bg-tint p-4 text-sm"}>
        <p className="text-ink">
          No tax rate set, so no estimate is shown here.
        </p>
        <p className="mt-1 text-ink-soft">
          {est.taxable_gain > 0 && (
            <>There is a realized gain of {inBase.format(est.taxable_gain)}. </>
          )}
          {est.realized_gain < 0 && (
            <>
              The realized result is a loss of{" "}
              {inBase.format(-est.realized_gain)}, which no rate would be applied
              to anyway.{" "}
            </>
          )}
          {est.dividends_gross_estimated > 0 && (
            <>
              {inBase.format(est.dividends_gross_estimated)} of dividends still
              show the market&rsquo;s gross figure.{" "}
            </>
          )}
          Set your rate in Profile &rarr; Tax.
        </p>
      </div>
    );
  }

  return (
    <div className={cardClass + " bg-tint p-4"}>
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <span className="text-[0.65rem] uppercase tracking-[0.12em] text-olive">
          Estimated tax{est.country ? ` · ${est.country}` : ""}
        </span>
        {est.total != null ? (
          <span className="text-sm text-ink-soft">
            <span className="font-semibold text-ink">{inBase.format(est.total)}</span>{" "}
            estimated, and counted in none of the totals above
          </span>
        ) : (
          <span className="text-sm text-warn">
            No total: you have not set a rate for {est.missing_rates.join(" or ")},
            and adding up only the half that can be worked out would understate it.
          </span>
        )}
      </div>

      <div className="mt-3 space-y-1 text-sm text-ink-soft">
        {/* A loss says so in its own words. Running the rate over a negative
            base would print a credit the reader does not have, and showing
            "gain 0.00" would hide that something was sold at a loss at all. */}
        {/* Each line is gated on its OWN figure, not merely on a rate being
            set: with a dividend to estimate and nothing sold, "Realized gain
            EUR 0 at 26% = EUR 0" is a true row that says nothing. */}
        {est.capital_gains_tax != null && est.realized_gain < 0 && (
          <p>
            Realized result is a loss of{" "}
            <span className="font-semibold text-down">
              {inBase.format(-est.realized_gain)}
            </span>{" "}
            (nothing estimated on it)
          </p>
        )}
        {est.capital_gains_tax != null && est.realized_gain > 0 && (
          <p>
            Realized gain {inBase.format(est.taxable_gain)} at{" "}
            <span className="text-ink">{est.capital_gains_rate}%</span> ={" "}
            <span className="font-semibold text-ink">
              {inBase.format(est.capital_gains_tax)}
            </span>
          </p>
        )}
        {est.dividend_withholding != null && est.dividends_gross_estimated > 0 && (
          <p>
            Gross dividends {inBase.format(est.dividends_gross_estimated)} at{" "}
            <span className="text-ink">{est.dividend_withholding_rate}%</span> ={" "}
            <span className="font-semibold text-ink">
              {inBase.format(est.dividend_withholding)}
            </span>
            {est.dividends_recorded_net > 0 && (
              <span className="text-ink-faint">
                {" "}
                · the {inBase.format(est.dividends_recorded_net)} you corrected by
                hand is already net and is left alone
              </span>
            )}
          </p>
        )}
      </div>

      {/* The caveats come from the backend, not from this file: the page, the
          chat and any outside assistant read the same list, and a caveat kept
          only in the UI is one the chat would confidently omit. */}
      <ul className="mt-3 space-y-1 text-xs text-ink-faint">
        {est.caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </div>
  );
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso + "T00:00:00").toLocaleDateString(locale) : "";
}

// A position is only worth flagging once it has had time to drift. Below this
// the note would be noise on every freshly entered row.
const STALE_AFTER_DAYS = 30;

/* What the ledger form lets the watchlist do to it, and — as much to the
   point — what the watchlist cannot do to it.

   The second half of the cycle the suggestion card started: card → watchlist →
   buy. "Buy" is not a broker instruction, because no broker is connected and
   none ever will be; a buy in this app is a LEDGER ENTRY about a purchase that
   already happened. So a row does not buy anything. It opens the form the
   reader has used before, carrying the one thing it knows — which fund — and
   gets out of the way. How many, at what price, where and when are facts only
   the reader has, and a prefilled guess at any of them would be a number this
   app invented.

   The routing was the choice worth arguing. The other candidate was to send
   "record a buy of X" to the chat and let `record_transaction` propose a card;
   it was rejected because the chat proposes where there is JUDGEMENT, and there
   is none here — the reader knows what they bought. Routing a deterministic
   action through a model buys a round trip, a wait, and a model's chance of
   being wrong about a form that already exists.

   A HANDLE rather than a prop the form watches. Pressing the button is an
   EVENT, and its whole answer — fill the boxes it can vouch for, scroll, put
   the caret in the first box only the reader can fill — happens once, then.
   Kept as state it would have to be replayed by an effect, and pressing the
   same row twice would need a nonce to look like a change. */
type BuyForm = {
  prefillFrom: (item: WatchlistItem) => void;
};

function staleNote(r: PortfolioData["rows"][number]): string | null {
  const days = r.quantity_age_days;
  if (days == null || days < STALE_AFTER_DAYS || !r.observed_on) return null;
  const when = fmtDate(r.observed_on);
  return r.market_value == null
    ? `value from ${when} (${days} days): nothing can price this, only you can refresh it`
    : `priced today, but ${days} days since anyone confirmed you hold this many (${when})`;
}

export default function Portfolio({
  focus,
  onFocused,
}: {
  /** "ledger" when the reader pressed "− buys" or "+ sells/dividends" on an
      account page. Both terms come from the same list, so both land in the
      same place — which is the honest answer: the ledger does not keep buys
      and sells apart, and pretending otherwise would invent a distinction the
      reader would then look for. */
  focus: Focus | null;
  onFocused: () => void;
}) {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [txs, setTxs] = useState<Transaction[]>([]);
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  /* One extra call on a page that already loaded institutions, and it is part
     of the fix rather than a nicety. The ledger form's institution select is
     now required, and a required field that says nothing back is paperwork;
     each entry carrying the cash it will spend turns picking into the reader
     finding out whether the money is there, in the one moment they care. */
  const [cash, setCash] = useState<CashPosition[]>([]);
  const [anchors, setAnchors] = useState<CashAnchor[]>([]);
  const [listing, setListing] = useState<Record<string, string>>({});
  // The two are siblings: the watchlist raises the intent, the ledger form
  // answers it, and neither has to know the other is on the page.
  const buyForm = useRef<BuyForm>(null);
  const [loading, setLoading] = useState(true);
  const [pricing, setPricing] = useState(false);
  // The ledger, as a place to be sent to. Positions and the look-through sit
  // above it and are not what "− buys €610" is about.
  const ledgerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void load(false);
  }, []);

  async function load(live: boolean) {
    if (live) setPricing(true);
    else setLoading(true);
    setError(null);
    try {
      const [p, t, i, c, a, l] = await Promise.all([
        getPortfolio(live),
        getTransactions(),
        getInstitutions(),
        getCashPositions(),
        getAllCashAnchors(),
        getListingCurrencies(),
      ]);
      setData(p);
      setTxs(t);
      setInstitutions(i);
      setCash(c);
      setAnchors(a);
      setListing(l);
    } catch (err) {
      setError(apiError(err, "Could not load the portfolio. Is the backend running on :8000?"));
    } finally {
      setLoading(false);
      setPricing(false);
    }
  }

  // Arriving AT the ledger. Two waits, not one, and the second is the reason
  // this is not the three-liner Cash flow gets.
  //
  // The first is the same there: this component returns "Loading…" first, so
  // on the render that carries the focus there is no ledger to scroll to.
  //
  // The second is peculiar to this page. Cash flow fetches everything in one
  // `loadAll` and renders its sections already full, so where a heading lands
  // is where it stays. Here the two sections ABOVE the ledger — the
  // look-through and the watchlist — fetch on their own and grow the page
  // AFTER this effect has run, pushing the ledger down past a reader who has
  // already been delivered to it. Measured before this followed the growth:
  // the heading settled 758px down a 900px viewport, having been scrolled to
  // correctly and then left behind. So the scroll is repeated while the page
  // is still changing height, and stops when it stops.
  useEffect(() => {
    if (focus !== "ledger" || loading || !data) return;
    const el = ledgerRef.current;
    if (!el) return;
    // Consumed immediately: what follows is this effect's own business, and
    // leaving the focus set would re-arm the whole thing on the next render.
    onFocused();
    const settle = () => el.scrollIntoView({ behavior: "smooth", block: "start" });
    settle();
    const growing = new ResizeObserver(settle);
    growing.observe(document.body);
    // Deliberately outlives this effect rather than being torn down by its
    // cleanup — clearing the focus above re-runs it, and a cleanup would then
    // disconnect the observer a frame after it was attached, which is exactly
    // the bug it exists to fix. It disarms itself instead.
    window.setTimeout(() => growing.disconnect(), 2500);
  }, [focus, loading, data, onFocused]);

  if (loading) return <p className="text-ink-soft">Loading…</p>;
  if (error) return <p className="text-down">{error}</p>;
  if (!data) return null;

  // The P/L the column actually adds up to. It is NOT total_market − total_book:
  // a row nothing can price contributes its last observed value to the market
  // total and no P/L to the column, so subtracting the two totals silently
  // credits a month-old statement as if the market had said it. What that gap
  // IS gets its own line below, named.
  const pricedDelta = data.rows.reduce(
    (acc, r) => (r.delta != null ? acc + r.delta : acc),
    0,
  );
  const anyDelta = data.rows.some((r) => r.delta != null);
  const carried = data.rows.reduce(
    (acc, r) => (r.market_value == null ? acc + r.observed_value : acc),
    0,
  );

  return (
    <div className="space-y-10">
    <Section
      title="Portfolio"
      hint="Your investment positions (latest situation of each institution). Refresh to pull live market prices and see profit/loss vs the recorded value."
    >
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => load(true)} disabled={pricing} className={btnClass}>
          {pricing ? "Pricing…" : "↻ Refresh market prices"}
        </button>
        {data.priced && (
          <span className="text-sm text-ink-soft">
            Market{" "}
            <span className="font-semibold text-ink">
              {data.total_market != null ? money(data.base_currency).format(data.total_market) : "unknown"}
            </span>{" "}
            vs recorded {money(data.base_currency).format(data.total_book)}
            {anyDelta && (
              <span
                className={"ml-2 font-semibold " + toneClass(pricedDelta)}
              >
                {pricedDelta >= 0 ? "+" : ""}
                {money(data.base_currency).format(pricedDelta)}
                <span className="ml-1 text-xs font-normal text-ink-faint">
                  on priced rows
                </span>
              </span>
            )}
          </span>
        )}
        {/* Only beside a total: with nothing priced at all there is no
            "that total" on the page for this to be a part of, and the line
            read as a share of a number smaller than itself. */}
        {data.priced && carried > 0 && (
          <span className="text-xs text-ink-faint">
            {money(data.base_currency).format(carried)} of that total is what you last recorded, not priced
          </span>
        )}
        {!data.priced && (
          <span className="text-sm text-ink-soft">
            Recorded total <span className="font-semibold text-ink">{money(data.base_currency).format(data.total_book)}</span>
          </span>
        )}
        {(data.prices_as_of || data.fx_as_of) && (
          // Where these numbers came from, said once and outside the priced
          // branch. The FX date used to be nested inside the price date, so a
          // portfolio that was converted but not priced — an opaque position
          // recorded in dollars — put a EUR figure on screen with no rate date
          // anywhere near it. Provenance travels with every number, including
          // this one.
          <span className="text-xs text-ink-faint">
            {data.prices_as_of && <>prices as of {fmtDate(data.prices_as_of)}</>}
            {data.prices_as_of && data.fx_as_of && " · "}
            {data.fx_as_of && <>FX ECB {fmtDate(data.fx_as_of)}</>}
          </span>
        )}
        {(data.total_realized !== 0 || data.total_dividends !== 0) && (
          <span className="text-sm text-ink-soft">
            {data.total_realized !== 0 && (
              <>
                Realized P/L{" "}
                <span className={"font-semibold " + toneClass(data.total_realized)}>
                  {data.total_realized >= 0 ? "+" : ""}
                  {money(data.base_currency).format(data.total_realized)}
                </span>
              </>
            )}
            {data.total_dividends !== 0 && (
              <> · dividends collected {money(data.base_currency).format(data.total_dividends)}</>
            )}
          </span>
        )}
      </div>

      <TaxEstimatePanel est={data.tax_estimate} baseCurrency={data.base_currency} />

      <OmissionsNotice
        items={data.unresolved_omissions ?? []}
        arrivals={data.declared_instead ?? []}
        baseCurrency={data.base_currency}
      />

      {/* What no rate could be applied to at all — the pair to `fx_as_of` under
          the totals, which says which rate WAS applied. */}
      <UnconvertedNotice items={data.unconverted ?? []} baseCurrency={data.base_currency} />

      {data.rows.length === 0 ? (
        <EmptyState title="Nothing invested yet">
          Add an institution in Records → Wealth, then a dated situation and the holdings it
          contains. Give each one a ticker and this table fills in on its own.
        </EmptyState>
      ) : (
        // Dense view: the ruled-ledger treatment — alternating row tint,
        // hairline column rules, micro-caps headers. Chosen for the tables
        // where figures are read in columns.
        <div className={cardClass + " overflow-x-auto"}>
          <table className="w-full border-collapse text-left text-sm [&_td:not(:first-child)]:border-l [&_td:not(:first-child)]:border-hair [&_tbody_tr:nth-child(even)]:bg-tint">
            <thead>
              <tr className="border-b border-rule text-[0.65rem] uppercase tracking-[0.12em] text-olive">
                <th className="px-4 py-2 font-semibold">Asset</th>
                <th className="px-4 py-2 font-semibold">Institution</th>
                <th className="px-4 py-2 text-right font-semibold">Qty</th>
                <th className="px-4 py-2 text-right font-semibold">Avg cost</th>
                <th className="px-4 py-2 text-right font-semibold">Recorded</th>
                <th className="px-4 py-2 text-right font-semibold">Live price</th>
                <th className="px-4 py-2 text-right font-semibold">Worth now</th>
                <th className="px-4 py-2 text-right font-semibold">P/L vs recorded</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={i} className="border-b border-hair last:border-0">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-ink">{r.asset_name}</div>
                    <div className="text-xs text-ink-soft">
                      {[r.symbol, r.asset_class, dividendWord(r.distribution_policy, r.last_dividend)]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {r.currency_note && (
                      <div className="mt-0.5 text-[0.65rem] text-warn">
                        ⚠ {r.currency_note}. The listing wins; fix the field in Records
                      </div>
                    )}
                    {/* Two different things go stale, and saying "old" flattens
                        them: a priced row is worth today's money and only its
                        UNIT COUNT is as old as the photo, while a row nothing
                        can price is old in every respect. */}
                    {staleNote(r) && (
                      <div className="mt-0.5 text-[0.65rem] text-ink-faint">{staleNote(r)}</div>
                    )}
                    {r.closed_on && (
                      <div className="mt-0.5 text-[0.65rem] text-ink-soft">
                        disposed of on {fmtDate(r.closed_on)}, kept here so the exit
                        is visible
                      </div>
                    )}
                  </td>
                  {/* Null is an answer, not a missing name. This cell used to
                      print "?" — indistinguishable from a bank actually called
                      that, and silent about the one thing the reader needs to
                      know, which is that no situation can ever photograph this
                      position. The ledger list below says the same words. */}
                  <td className="px-4 py-2.5 text-ink-soft">
                    {r.institution ?? (
                      <span
                        className="text-ink-faint"
                        title="Held at no institution: no situation can photograph it and nothing can confirm it is still there. PAC targets that name no institution create these. Give the ledger row below an institution to attach it."
                      >
                        no institution
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right text-ink-soft">{r.quantity ?? "n/a"}</td>
                  <td
                    className="px-4 py-2.5 text-right text-ink-soft"
                    title={avgCostTitle(r)}
                  >
                    {r.avg_cost == null ? (
                      "n/a"
                    ) : r.cost_known ? (
                      <>
                        {money(data.base_currency).format(r.avg_cost)}
                        {r.cost_estimated && (
                          <span className="ml-1 text-[0.65rem] text-warn">est.</span>
                        )}
                      </>
                    ) : (
                      <span className="text-ink-faint">cost unknown</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right text-ink">{money(data.base_currency).format(r.book_value)}</td>
                  <td
                    className="px-4 py-2.5 text-right text-ink-soft"
                    title={r.as_of ? `Market close of ${fmtDate(r.as_of)}` : undefined}
                  >
                    {r.live_price == null
                      ? "unknown"
                      : r.currency && r.currency !== data.base_currency
                        ? `${r.live_price.toLocaleString(locale)} ${r.currency}`
                        : money(data.base_currency).format(r.live_price)}
                    {r.as_of && r.as_of !== data.prices_as_of && (
                      <div className="text-xs text-ink-faint">{fmtDate(r.as_of)}</div>
                    )}
                  </td>
                  {/* What the row is worth, and by whose authority. A market
                      price where there is one; where there is not, the figure
                      last recorded for the position — greyed, because it is an
                      observation and not a quote, and dated by the stale note
                      on the asset. Not always a photograph: a position born in
                      the ledger has only what was paid for it, so the wording
                      claims no snapshot. It used to print "—" here and count
                      that same number into the total above, which is a total
                      no row on the page could explain. */}
                  <td
                    className={
                      "px-4 py-2.5 text-right font-medium " +
                      (r.market_value != null ? "text-ink" : "text-ink-soft")
                    }
                    title={
                      r.market_value != null
                        ? undefined
                        : "Nothing can price this today: the last value recorded for this position, carried forward"
                    }
                  >
                    {money(data.base_currency).format(r.market_value ?? r.observed_value)}
                  </td>
                  <td
                    className={
                      "px-4 py-2.5 text-right font-medium " +
                      (r.cost_known ? toneClass(r.delta) : "text-ink-soft")
                    }
                    title={plTitle(r)}
                  >
                    {r.delta != null ? (
                      <>
                        {r.delta >= 0 ? "+" : ""}
                        {money(data.base_currency).format(r.delta)}
                        {r.delta_pct != null && (
                          <span className="ml-1 text-xs">({pctFmt.format(r.delta_pct)})</span>
                        )}
                        {!r.cost_known && (
                          <div className="text-[0.65rem] font-normal text-ink-faint">
                            since situation
                          </div>
                        )}
                      </>
                    ) : (
                      "unknown"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="max-w-[80ch] text-xs text-ink-faint">
        <em>Recorded</em> is what a position cost: the purchase price where you entered one,
        otherwise the value your last situation recorded (and then <em>Avg cost</em> says
        "cost unknown", because that is not a price you paid). <em>Worth now</em> is the other
        question: a market price where the market can give one, the last value recorded for
        the position where it cannot. <em>P/L vs recorded</em> compares the two only when a real
        quote priced the row. On a row nothing can price, the difference between the two
        columns is there to read, but a month-old statement is not a market and this app will
        not colour it green. Refreshing a price no longer overwrites a situation (that used to
        force P/L to zero): to record today's values, record a new situation.
      </p>
    </Section>

    {/* Reading before bookkeeping: positions, then what is really inside them,
        and only then the ledger you type into. */}
    <LookThroughSection />
    {/* Under the holdings and not inside them: a watchlist line is not a
        position. It counts toward no total on this page, which is exactly what
        makes it safe for the chat to propose one. */}
    <Watchlist onBuy={(i: WatchlistItem) => buyForm.current?.prefillFrom(i)} />
    <div ref={ledgerRef} className="scroll-mt-6">
    <BuysSection
      ref={buyForm}
      items={txs}
      institutions={institutions}
      cash={cash}
      anchors={anchors}
      listing={listing}
      base={data.base_currency}
      /* NOT `onChanged`. That calls `load`, which raises the page-level
         `loading` flag and replaces the whole section with "Loading…" — the
         form unmounts, and the quantity and price the reader typed by hand go
         with it. Which is the one thing making an institution from inside the
         form exists to avoid. The new row is folded into the list in place
         instead; it has no cash anchor yet by construction, so its entry in
         the select reads "no cash on record" with nothing else to fetch. */
      onInstitutionAdded={(made) => setInstitutions((prev) => [...prev, made])}
      owned={data.rows
        .filter((r) => r.symbol)
        .map((r) => ({
          symbol: r.symbol as string,
          name: r.asset_name,
          institution: r.institution,
        }))}
      onChanged={() => load(false)}
    />
    </div>
    </div>
  );
}

// Simple horizontal weight bar (0-100).
function WeightBar({ pct }: { pct: number }) {
  return (
    <div className="h-2 w-full rounded-full bg-tint">
      <div
        className="h-2 rounded-full bg-olive"
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  );
}

function AllocationList({
  title,
  items,
  noData,
}: {
  title: string;
  items: { name: string; pct: number }[];
  noData?: number;
}) {
  if (items.length === 0) return null;
  return (
    <div className={cardClass + " p-4"}>
      <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-soft">{title}</h4>
      <div className="space-y-2">
        {items.slice(0, 10).map((it) => (
          <div key={it.name} className="grid grid-cols-[8rem_1fr_3.5rem] items-center gap-2 text-sm">
            <span className="truncate text-ink" title={it.name}>{it.name}</span>
            <WeightBar pct={it.pct} />
            <span className="text-right tabular-nums text-ink-soft">{it.pct.toFixed(1)}%</span>
          </div>
        ))}
        {/* The share nothing could decompose gets its own bar, in a non-data
            tone. Never folded into the others and never normalised away: a
            chart that renormalised to 100% here would claim a precision the
            data does not have. */}
        {noData != null && noData > 0 && (
          <div className="grid grid-cols-[8rem_1fr_3.5rem] items-center gap-2 border-t border-hair pt-2 text-sm">
            <span className="truncate text-ink-faint">No data</span>
            <div
              className="h-2 w-full rounded-full"
              style={{
                backgroundImage:
                  "repeating-linear-gradient(45deg, var(--color-rule) 0 3px, transparent 3px 6px)",
                maskImage: `linear-gradient(to right, #000 ${Math.min(noData, 100)}%, transparent 0)`,
                WebkitMaskImage: `linear-gradient(to right, #000 ${Math.min(noData, 100)}%, transparent 0)`,
              }}
            />
            <span className="text-right tabular-nums text-ink-faint">{noData.toFixed(1)}%</span>
          </div>
        )}
      </div>
    </div>
  );
}

/** Asset class x region, shaded by weight. A grid of magnitudes takes one hue
    with more-is-darker, never a different colour per cell. */
function ExposureMatrix({ cells }: { cells: MatrixCell[] }) {
  if (cells.length === 0) return null;
  const classes = [...new Set(cells.map((c) => c.asset_class))];
  const regionTotals = new Map<string, number>();
  for (const c of cells) regionTotals.set(c.region, (regionTotals.get(c.region) ?? 0) + c.pct);
  const regions = [...regionTotals.entries()].sort((a, b) => b[1] - a[1]).map(([r]) => r);
  const max = Math.max(...cells.map((c) => c.pct), 1);
  const at = (k: string, r: string) =>
    cells.find((c) => c.asset_class === k && c.region === r)?.pct ?? 0;

  return (
    <div className={cardClass + " overflow-x-auto p-4"}>
      <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-soft">
        Asset class × region (% of portfolio)
      </h4>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-[0.65rem] uppercase tracking-[0.1em] text-ink-soft">
            <th className="py-1 pr-3 text-left font-medium">Class</th>
            {regions.map((r) => (
              <th key={r} className="px-2 py-1 text-right font-medium">{r}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {classes.map((k) => (
            <tr key={k}>
              <td className="py-1 pr-3 text-ink">{k}</td>
              {regions.map((r) => {
                const v = at(k, r);
                return (
                  <td
                    key={r}
                    className="px-2 py-1 text-right tabular-nums text-ink"
                    style={{
                      backgroundColor:
                        v > 0 ? `color-mix(in oklab, var(--color-olive) ${Math.round((v / max) * 45)}%, transparent)` : undefined,
                    }}
                  >
                    {v > 0 ? `${v.toFixed(1)}%` : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LookThroughSection() {
  const [data, setData] = useState<PortfolioComposition | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(refresh: boolean) {
    setLoading(true);
    setError(null);
    try {
      setData(await getPortfolioComposition(refresh));
    } catch (err) {
      setError(apiError(err, "Could not load the composition (sources may be unreachable)."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(false);
  }, []);

  return (
    <Section
      title="Look-through (real exposure)"
      note="From the issuers’ own files where they publish them, justETF and Yahoo otherwise. Cached 15 days."
      explain={{
        question: "What is the look-through?",
        text: "What is really inside your funds: countries, sectors, and the issuers you hold through more than one of them.",
      }}
    >
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => load(true)} disabled={loading} className={btnClass}>
          {loading ? "Fetching…" : "↻ Update composition"}
        </button>
        {data && (
          <span className="text-sm text-ink-soft">
            Coverage{" "}
            <span className="font-semibold text-ink">
              {data.coverage_pct.toFixed(1)}%
            </span>{" "}
            of the portfolio decomposed
          </span>
        )}
      </div>
      {error && <p className="text-down">{error}</p>}
      {loading && !data && <p className="text-ink-soft">Loading composition…</p>}

      {data && (
        <>
          {/* Coverage first: every percentage below is a share of the WHOLE
              portfolio, so the reader must see how much of it was decomposed
              before reading any of them. */}
          <div className={cardClass + " p-4"}>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-soft">
                How much of the portfolio we can see inside
              </h4>
              <span className="text-sm tabular-nums text-ink">
                {data.coverage_pct.toFixed(1)}% decomposed
              </span>
            </div>
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-tint">
              <div className="h-3 bg-olive" style={{ width: `${data.coverage_pct}%` }} />
              <div
                className="h-3 flex-1"
                style={{
                  backgroundImage:
                    "repeating-linear-gradient(45deg, var(--color-rule) 0 3px, transparent 3px 6px)",
                }}
              />
            </div>
            <p className="mt-2 text-xs text-ink-faint">
              Percentages below are shares of the whole portfolio, so they add up to the
              decomposed part, not to 100%.
            </p>

            {/* What the backend knows about the shape of its own answer: an
                axis that came back empty and why, an overlap built from
                holdings lists of two different depths. It travels with the
                figures rather than sitting in a fixed caption, because it is
                only true some of the time. */}
            {(data.notes ?? []).map((n) => (
              <p key={n} className="mt-2 border-l-2 border-rule pl-2 text-xs text-ink-soft">
                {n}
              </p>
            ))}

            {/* Naming names: a coverage number alone does not tell you which
                position is missing, and that is the one thing you can act on. */}
            <div className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <div>
                <h5 className="mb-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-olive">
                  Looked inside
                </h5>
                <ul className="space-y-1 text-sm">
                  {data.rows
                    .filter((r) => r.decomposed)
                    .map((r) => (
                      <li key={r.symbol ?? r.asset_name} className="flex justify-between gap-3">
                        <span className="truncate text-ink" title={r.resolved_name ?? undefined}>
                          {r.asset_name}
                        </span>
                        <span className="shrink-0 tabular-nums text-ink-soft">
                          {r.weight_pct.toFixed(1)}%
                          <span className="ml-1.5 text-ink-faint">{r.source}</span>
                        </span>
                      </li>
                    ))}
                  {data.rows.every((r) => !r.decomposed) && (
                    <li className="text-ink-faint">Nothing yet.</li>
                  )}
                </ul>
              </div>
              <div>
                <h5 className="mb-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-soft">
                  Not decomposed
                </h5>
                <ul className="space-y-1 text-sm">
                  {data.rows
                    .filter((r) => !r.decomposed)
                    .map((r) => (
                      <li key={r.symbol ?? r.asset_name} className="flex justify-between gap-3">
                        <span className="truncate text-ink-soft" title={r.error ?? undefined}>
                          {r.asset_name}
                        </span>
                        <span className="shrink-0 tabular-nums text-ink-faint">
                          {r.weight_pct.toFixed(1)}%
                        </span>
                      </li>
                    ))}
                  {data.rows.every((r) => r.decomposed) && (
                    <li className="text-ink-faint">Everything is covered.</li>
                  )}
                </ul>
                <p className="mt-2 text-xs text-ink-faint">
                  Single stocks and crypto have nothing inside them to look at. A fund listed
                  here usually just needs its ISIN: add it to the holding in Records → Wealth.
                </p>
              </div>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <AllocationList
              title="Countries (% of portfolio)"
              items={data.countries}
              noData={data.undecomposed_pct}
            />
            <AllocationList
              title="Sectors (% of portfolio)"
              items={data.sectors}
              noData={data.undecomposed_pct}
            />
            <AllocationList
              title="Issuers (% of portfolio)"
              items={data.companies ?? []}
            />
            <AllocationList
              title="Currency exposure (% of portfolio)"
              items={data.currencies ?? []}
              noData={data.undecomposed_pct}
            />
          </div>

          <ExposureMatrix cells={data.matrix ?? []} />

          <p className="text-xs text-ink-faint">
            Currency exposure follows the country each company belongs to, not where it earns
            its revenue, and ignores share-class hedging: a EUR-hedged fund still shows the
            currencies of what it holds.
          </p>

          {data.overlap.length > 0 && (
            <div className={cardClass + " p-4"}>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Overlap: same stock inside 2+ funds
              </h4>
              {/* Say what this is measured on: the sources publish a top-10 per
                  fund, so a stock held by both but ranked 11th in one of them is
                  invisible here. This list is a floor, not the whole truth. */}
              <p className="mb-3 mt-1 text-xs text-ink-faint">
                Complete for funds resolved from their issuer's own holdings file; for funds
                covered by a third party it only sees the published top holdings, so the real
                overlap is larger there.
              </p>
              <ul className="space-y-1.5 text-sm">
                {data.overlap.slice(0, 10).map((o) => (
                  <li key={o.name} className="flex items-baseline justify-between gap-3">
                    <span className="text-ink">
                      {o.name}
                      <span className="ml-2 text-xs text-ink-faint">via {o.funds.join(", ")}</span>
                    </span>
                    <span className="tabular-nums font-medium text-ink">{o.pct.toFixed(2)}%</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

        </>
      )}
    </Section>
  );
}


/* The sentinel the select uses for "make one now" — never a value that reaches
   the payload, only a branch in the change handler. */
const ADD_INSTITUTION = "__add__";

/* What one entry in the institution select says after its name, and the reason
   the required field does not read as paperwork.

   `anchor_date` decides the wording, NOT `projected`. An institution with no
   cash anchor comes back `projected: 0.0, anchor_date: null`, and that zero
   means NOT ON RECORD rather than empty — printing it as "0.00 available"
   would be the app stating a balance it has never been told. The same
   distinction the table above draws between a cost of zero and COST UNKNOWN.

   Cents, not whole units: this figure exists to be compared against
   what the reader is about to spend, and rounding both sides hides exactly the
   answer they came for. */
function cashNote(p: CashPosition | undefined): string {
  if (!p || p.anchor_date == null) return "no cash on record";
  return `${money(p.base_currency, "cents").format(p.projected)} available`;
}

function BuysSection({
  items,
  institutions,
  cash,
  anchors,
  listing,
  base,
  owned,
  onChanged,
  onInstitutionAdded,
  ref,
}: {
  items: Transaction[];
  institutions: Institution[];
  /** Projected cash per institution, so each option in the select carries what
      it will spend. An institution made inline has no entry here until the
      next full load, which is right: it has no anchor either, and `cashNote`
      says so rather than inventing a balance for it. */
  cash: CashPosition[];
  /** Every account's cash anchors and the listing currencies the price cache
      knows: what the two currency boxes propose before the reader types. */
  anchors: CashAnchor[];
  listing: Record<string, string>;
  /** The base: what an entry on an account with no anchor is proposed in. */
  base: string;
  /** What you already hold — the first lane of the picker, and the one that
      makes a ledger entry land on the right position instead of beside it. */
  owned: { symbol: string; name: string; institution?: string | null }[];
  onChanged: () => Promise<void> | void;
  /** A new institution, made from inside this form, folded into the page's
      list WITHOUT the reload that would unmount this form mid-entry. */
  onInstitutionAdded: (made: Institution) => void;
  /** How a watchlist row reaches this form. See `BuyForm`. */
  ref?: Ref<BuyForm>;
}) {
  const [editId, setEditId] = useState<number | null>(null);
  const [kind, setKind] = useState("buy");
  const [date, setDate] = useState(todayISO());
  const [picked, setPicked] = useState("");
  const [assetName, setAssetName] = useState("");
  const [pickNote, setPickNote] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [fees, setFees] = useState("");
  /* The two currencies an entry has. The price's is the listing's, and the
     account's is what the fees and the money that moved are in. Each is the
     reader's choice once they made one (null until then) and otherwise the
     proposal worked out below. `debit` is that money when the two differ and
     the reader has the figure from their statement; left blank, the backend
     works it out at the ECB rate of the entry's date and says which day. */
  const [priceCurrencyChoice, setPriceCurrencyChoice] = useState<string | null>(null);
  const [currencyChoice, setCurrencyChoice] = useState<string | null>(null);
  // Listing currencies a dated quote taught this form after the page loaded.
  const [learned, setLearned] = useState<Record<string, string>>({});
  const [debit, setDebit] = useState("");
  const [priceNote, setPriceNote] = useState<string | null>(null);
  const [fetchingPrice, setFetchingPrice] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The inline "add where you keep it" field. Deliberately HERE and not a link
  // to Records → Wealth: by the time this matters the reader has typed a
  // quantity and a price by hand — the watchlist prefill leaves both blank on
  // purpose — and navigating away spends that.
  const [addingInstitution, setAddingInstitution] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("");
  const [creatingInstitution, setCreatingInstitution] = useState(false);
  const formRef = useRef<HTMLDivElement | null>(null);
  const quantityRef = useRef<HTMLInputElement | null>(null);
  const newNameRef = useRef<HTMLInputElement | null>(null);

  /* Two views of one row used to disagree. The table above printed "?" for a
     position held nowhere while this list dropped the institution silently —
     `.filter(Boolean)` removed the undefined — so the same row looked like it
     had a place in one view and no place at all three inches below. */
  const instName = (id: number | null) =>
    id == null ? "no institution" : institutions.find((i) => i.id === id)?.name;

  const cashFor = (id: number | null) =>
    id == null ? undefined : cash.find((c) => c.institution_id === id);

  /* Exactly one institution is not a choice, so it is not put as one.
     Contrast the watchlist prefill three functions down, which leaves quantity
     and price blank because a default for either would be this app inventing a
     number: here a default is the only answer there is. This is the state a
     row saved before this rule was created in: its institution already
     existed, and the select simply opened on blank.

     DERIVED, not an effect that writes the id into state. `picked` is what the
     reader has actually chosen and stays empty until they choose; the fallback
     is recomputed on every render, so it is right the moment a first
     institution appears — including the one made inline below — with no
     cascading render and nothing to keep in step. */
  const soleInstitutionId =
    institutions.length === 1 ? String(institutions[0].id) : "";
  const institutionId = picked || soleInstitutionId;

  function reset() {
    setEditId(null);
    setKind("buy");
    setDate(todayISO());
    setPicked("");
    setAddingInstitution(false);
    setNewName("");
    setNewType("");
    setAssetName("");
    setSymbol("");
    setQuantity("");
    setUnitPrice("");
    setFees("");
    setPriceCurrencyChoice(null);
    setCurrencyChoice(null);
    setDebit("");
    setPriceNote(null);
    // Cleared with the rest: the pick note is advice about a field, and a
    // sentence about the ticker box hanging over an empty ticker box is a
    // note about nothing.
    setPickNote(null);
  }

  /* A watchlist row arriving. It fills the two things it can vouch for and
     leaves the rest blank ON PURPOSE — quantity, price, institution and, where
     the suggestion carried no symbol, the ticker — because those are the
     reader's to state, and a plausible default for any of them would be this
     app inventing a number.

     THE TICKER IS THE ONE THAT NEEDS SAYING. A watchlist line is identified by
     an ISIN out of the local registry; an ISIN names the fund and does not
     price it, and the same fund carries a different ticker on every exchange it
     is listed on. So the box is filled only when the suggestion happened to
     carry a symbol from the live lookup, and even then it is labelled as the
     hint it is. Left empty, the note says why — an unexplained empty box in a
     form that filled itself reads as an oversight, and an oversight is
     corrected by guessing. A share's line is the other way round (brief AG):
     no ISIN, and its symbol IS the identity, the one Yahoo lists it under, so
     the box is filled with it and the note says where it came from.

     AND THE ROW DOES NOT MOVE. Recording a purchase says nothing about whether
     the idea is still an idea: a first tranche is a common thing to buy. So the
     watchlist line stays until the reader drops it, and the note says so. A row
     that vanished because the app inferred something is the silent deletion
     this codebase refuses everywhere else. */
  useImperativeHandle(ref, () => ({
    prefillFrom(item) {
      reset();
      setAssetName(item.name);
      setSymbol(item.symbol ?? "");
      // A share's line (brief AG) has no ISIN and its symbol is the identity,
      // so its note says so; a fund's says what it always said.
      setPickNote(prefillNote(item));
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      quantityRef.current?.focus({ preventScroll: true });
    },
  }));

  function startEdit(t: Transaction) {
    setEditId(t.id);
    setKind(t.kind);
    setDate(t.date);
    // A row with no institution — the PAC writes those legitimately — opens
    // with the field empty and cannot be saved until one is picked. That is
    // the repair path: attaching an institution is a one-field edit.
    setPicked(t.institution_id ? String(t.institution_id) : "");
    setAddingInstitution(false);
    setAssetName(t.asset_name);
    setSymbol(t.symbol ?? "");
    setQuantity(String(t.quantity));
    setUnitPrice(String(t.unit_price));
    // A stored entry's currencies are what it says it moved, not a proposal:
    // moving its date or its account does not rewrite them.
    setCurrencyChoice(t.currency);
    setPriceCurrencyChoice(t.price_currency ?? t.currency);
    if (t.kind === "close") {
      // A close keeps its proceeds in the box that holds them.
      setFees(String(t.amount));
      setDebit("");
    } else {
      setFees(t.fees ? String(t.fees) : "");
      // A figure only a statement can explain comes back into the box; one the
      // row itself derives does not, so that changing the quantity or the date
      // works it out again. `statedAmount.wasStated` is what tells them apart,
      // and it does it without a provenance column: `fx_as_of` is null for BOTH
      // a derived and a stated same-currency amount, but the row's own figures
      // are not.
      setDebit(debitOnEdit(t));
    }
  }

  /* The first institution, made from inside the form that needs one.

     `POST /api/institutions` had exactly one caller — the Institutions list in
     Records → Wealth — and this is the second. It is not a shortcut to that
     page: it is the same act with the reader's half-typed ledger row still on
     screen, and NOTHING above is touched. Sending them to Records instead
     would spend the quantity and the price they typed by hand, which the
     watchlist prefill deliberately leaves for them to type. */
  async function createAndSelect() {
    const name = newName.trim();
    if (!name) return;
    setCreatingInstitution(true);
    setError(null);
    try {
      const made = await createInstitution({ name, type: newType.trim() || null });
      onInstitutionAdded(made);
      setPicked(String(made.id));
      setAddingInstitution(false);
      setNewName("");
      setNewType("");
    } catch (err) {
      setError(apiError(err, "Could not add it."));
    } finally {
      setCreatingInstitution(false);
    }
  }

  // Backfilling an old purchase is the common case, and the one thing you
  // genuinely cannot remember is the price on the day. We already fetch
  // historical closes for PAC executions, so the same call turns "what did
  // VWCE cost on 12 March?" into a date plus a quantity. The close is a
  // DEFAULT, not the truth: your fill may differ by a few cents and carries
  // fees, so it stays editable.
  async function fillPriceOnDate() {
    if (!symbol.trim() || !date) return;
    setFetchingPrice(true);
    setPriceNote(null);
    setError(null);
    try {
      const q = await getQuote(symbol.trim(), date);
      setUnitPrice(String(q.price));
      // The price is in the listing's currency; the cache knows it once
      // anything has priced the symbol, and then the proposal follows it — a
      // currency the reader picked by hand stays theirs.
      const listed = q.currency;
      if (listed) setLearned((prev) => ({ ...prev, [q.symbol]: listed }));
      setPriceNote(
        `${q.name ?? q.symbol}, close of ${fmtDate(q.as_of)}: ${q.price}${q.currency ? ` ${q.currency}` : ""}. Edit it if your fill differed.`,
      );
    } catch (err) {
      setError(apiError(err, "No price found for that ticker on that date."));
    } finally {
      setFetchingPrice(false);
    }
  }

  // A close says a position is gone in its entirety and what came back, so it
  // needs a name and proceeds and nothing else — the rows that most need an
  // exit are exactly the ones with no ticker and no units to sell.
  /* The proposals. The account's currency is that of its anchor in force on
     the entry's date (or its first), and the base only for an account with no
     anchor at all. The price's is the listing's when the price
     cache knows it; otherwise the account's, which is the one-currency entry
     every row was before a listing could differ. */
  const currency =
    currencyChoice ??
    accountCurrencyOn(anchors, institutionId ? Number(institutionId) : null, date) ??
    base;
  const priceCurrency =
    priceCurrencyChoice ?? listingCurrencyOf({ ...listing, ...learned }, symbol) ?? currency;

  const isClose = kind === "close";
  const needs = transaction(kind, isClose);
  // Two currencies on one entry: the money that moved cannot be read off the
  // price here, because that takes the rate of the entry's own day. The box for
  // it appears either way now — see `statedAmount.ts` for what it used to cost
  // that it only appeared when the two differed.
  const acrossCurrencies = !isClose && isAcross(currency, priceCurrency);
  // What the entry works out to from the figures beside it, when they are all
  // in one currency: the placeholder in the box, and the figure the overspend
  // warning is measured against. The rule is `crud._transaction_columns`'s, and
  // `statedAmount.derivedAmount` is the one copy of it on this side.
  const derived = derivedAmount({
    kind,
    quantity: Number(quantity) || 0,
    unit_price: Number(unitPrice) || 0,
    fees: Number(fees) || 0,
  });

  /* What this entry will take out of the picked institution's cash, against
     what the records say is there.

     SAID, NEVER REFUSED. Records that are behind is exactly the case the
     reader is correcting, and refusing here would make the app pretend it
     knows the balance — the same reasoning `tools._settled_position` already
     applies to a disposal against a position with too few units. Only a buy
     spends; a sell, a dividend and a close all pay in. And only where there is
     an anchor: with none there is no figure to be more than. */
  const spend =
    kind !== "buy"
      ? 0
      : debit !== ""
        ? Number(debit) || 0 // what the reader says the account moved by
        : acrossCurrencies
          ? 0 // unknown until the backend works it out at the day's rate
          : derived;
  const purse = cashFor(institutionId ? Number(institutionId) : null);
  // The register's projection is in the base its payload declares; a spend in
  // another currency is not comparable with it here, and is not compared.
  const overspend =
    purse &&
    purse.anchor_date != null &&
    currency.trim().toUpperCase() === purse.base_currency.toUpperCase() &&
    spend > purse.projected
      ? purse
      : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const refused = refusal(needs, {
      assetName, fees, symbol, quantity, unitPrice, institutionId, currency, priceCurrency,
    });
    /* The reason, not the rule — and last, so the sentence appears exactly
       when the institution is the one thing left rather than over a form the
       reader has barely started.

       The select's placeholder is `disabled` so a blank cannot be chosen back,
       and this catches the case that cannot: a form nobody has touched, which
       is how the row now in the database was made. Both halves are needed;
       submit-time validation alone leaves a pickable option that writes a
       null. */
    if (refused) {
      setError(refused);
      return;
    }
    setSubmitting(true);
    setError(null);
    const payload = isClose
      ? {
          kind,
          date,
          institution_id: Number(institutionId),
          asset_name: assetName.trim(),
          symbol: symbol.trim().toUpperCase() || null,
          // `fees` doubles as the proceeds box for a close: one number, and it
          // has to be given — zero is allowed, but it must be SAID, because
          // that is the whole difference between a disposal and an omission.
          amount: Number(fees),
          currency: currency.trim(),
        }
      : {
          kind,
          date,
          institution_id: Number(institutionId),
          asset_name: assetName.trim(),
          symbol: symbol.trim().toUpperCase(),
          quantity: Number(quantity),
          unit_price: Number(unitPrice),
          fees: fees ? Number(fees) : 0,
          currency: currency.trim(),
          price_currency: priceCurrency.trim(),
          // What the box holds, whatever the currencies are. Empty means
          // "work it out" — which is what keeps the cash figure in step with
          // an edited quantity — and a figure means the reader is stating what
          // the account moved by. This used to be gated on `acrossCurrencies`,
          // so a one-currency row always sent null and a figure off a contract
          // note was replaced by quantity x price on the next save of any kind.
          amount: debit !== "" ? Number(debit) : null,
        };
    try {
      if (editId != null) await updateTransaction(editId, payload);
      else await createTransaction(payload);
      reset();
      await onChanged();
    } catch (err) {
      setError(apiError(err, "Save failed."));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(t: Transaction) {
    if (!window.confirm(`Delete ${t.kind} "${t.asset_name}" of ${t.date}?`)) return;
    setError(null);
    try {
      await deleteTransaction(t.id);
      if (editId === t.id) reset();
      await onChanged();
    } catch (err) {
      setError(apiError(err, "Delete failed."));
    }
  }

  return (
    <div ref={formRef}>
    <Section
      title="Transactions (ledger)"
      hint="What you paid, and what came back: the only place a real profit can come from."
      note="Without a buy here, the P/L above measures movement since the last situation rather than gain. Rows marked ‘estimated’ came from market closes or gross dividends. Correct them with the real broker amounts."
      explain={{
        question: "How are sells and dividends counted?",
        text: "A sell removes units at average cost and books the difference; a dividend credits cash.",
      }}
    >
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
        <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="buy">buy</option>
          <option value="sell">sell</option>
          <option value="dividend">dividend</option>
          <option value="close">close</option>
        </select>
        <input className={inputClass} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        {/* A buy has to come from somewhere. A row with neither institution
            column set is skipped by the cash register — it keeps the entries
            belonging to the institution it is computing, and null matches no
            id there is — while the position it creates is counted in full, so
            the purchase adds its own cost to the net worth instead of moving
            it. Measured at 1000 cash: a 100 buy naming nobody read 1100.

            Three states, and only one of them is a question. Nothing on record
            and the only entry is the ACT, because there is nothing to choose
            between. Exactly one and it is already picked, because there is no
            ambiguity to preserve. Two or more and the placeholder stays,
            `disabled` so it cannot be chosen back.

            The wording is the reader's, not the model's: "institution…" was
            the column's name. This matches what Records → Wealth already says
            of the same list — "Banks, brokers… Pick one to track its cash and
            record its investments". */}
        <select
          className={inputClass}
          value={institutionId}
          {...marks(needs, "institutionId")}
          title="Where the position is held, and whose cash pays for it"
          onChange={(e) => {
            if (e.target.value === ADD_INSTITUTION) {
              setAddingInstitution(true);
              // Focused next paint, once the field below actually exists.
              setTimeout(() => newNameRef.current?.focus(), 0);
              return;
            }
            setAddingInstitution(false);
            setPicked(e.target.value);
          }}
        >
          <option value="" disabled>
            Where do you keep it?
          </option>
          {institutions.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name} · {cashNote(cashFor(i.id))}
            </option>
          ))}
          <option value={ADD_INSTITUTION}>+ Add where you keep it</option>
        </select>
        {/* The same picker as the situations form, with one lane added that
            matters more here than anywhere else: a ledger entry is matched to
            a position by EXACT ticker, so a spelling that differs by one
            character starts a second position for the same fund rather than
            adding to the one you hold. Choosing from what you own cannot
            miss. */}
        <InstrumentPicker
          value={assetName}
          onChange={setAssetName}
          owned={owned}
          placeholder="Asset (type to search)"
          mark={marks(needs, "assetName")}
          onPick={(c) => {
            setAssetName(c.name);
            if (c.source === "catalogue") {
              // No symbol to offer, and the ledger matches on symbol alone.
              setPickNote(`${c.isin}: the ticker is still yours to give.`);
              return;
            }
            setSymbol(c.symbol);
            setPickNote(
              c.source === "owned"
                ? null // Known-good by definition: it came off the position.
                : `${c.symbol}: check it matches the position you are adding to.`,
            );
          }}
        />
        <input className={inputClass + " w-32"} placeholder="Ticker or ISIN" {...marks(needs, "symbol")} title="Yahoo ticker with exchange suffix (e.g. VWCE.MI) or the fund's ISIN. It must match the position's symbol in Wealth" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        <input ref={quantityRef} className={inputClass + " w-24"} type="number" step="any" min="0" aria-label="Quantity" placeholder="Qty" {...marks(needs, "quantity")} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        {!isClose && (
          <input className={inputClass + " w-28"} type="number" step="any" min="0" aria-label={kind === "dividend" ? "Dividend per share" : "Price"} {...marks(needs, "unitPrice")} value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} />
        )}
        {!isClose && (
          <input
            className={inputClass + " w-20"}
            placeholder="currency"
            {...marks(needs, "priceCurrency")}
            list={CURRENCY_LIST}
            title="The currency the price is in: the listing's (USD for a New York share, GBp for pence in London)"
            value={priceCurrency}
            onChange={(e) => setPriceCurrencyChoice(e.target.value)}
          />
        )}
        <button
          type="button"
          hidden={isClose}
          onClick={fillPriceOnDate}
          disabled={fetchingPrice || !symbol.trim() || !date}
          className="rounded-sm border border-rule px-2 py-2 text-xs text-ink-soft transition hover:border-olive hover:text-olive disabled:opacity-50"
        >
          {fetchingPrice ? "…" : "↻ price on date"}
        </button>
        <input
          className={inputClass + (isClose ? " w-32" : " w-24")}
          type="number"
          step="any"
          min="0"
          placeholder={isClose ? "Proceeds" : "Fees"}
          {...marks(needs, "fees")}
          title={
            isClose
              ? "What came back. Zero is allowed, but it has to be said: that is the difference between selling something and forgetting it."
              : "Broker fees and commissions"
          }
          value={fees}
          onChange={(e) => setFees(e.target.value)}
        />
        <input
          className={inputClass + " w-20"}
          placeholder="currency"
          {...marks(needs, "currency")}
          list={CURRENCY_LIST}
          title={
            isClose
              ? "The currency the proceeds reached the account in"
              : "The currency of the account: what the fees and the money that moved are in"
          }
          value={currency}
          onChange={(e) => setCurrencyChoice(e.target.value)}
        />
        {/* Always, except for a close — whose proceeds have their own box.
            It used to appear only when the two currencies DIFFERED, which left
            the ordinary case with no way to say what the account really moved
            by: a buy stored at 307.42 came back 300.00 after a save that
            changed nothing, and the note above telling the reader to correct
            an estimated row with the real broker amount had no box to do it
            in. Empty is a request — "work it out" — so the placeholder says
            what that would be rather than leaving the box looking unanswered. */}
        {!isClose && (
          <input
            className={inputClass + " w-48"}
            type="number"
            step="any"
            min="0"
            // What the empty box MEANS, rather than a label for the box: left
            // alone it is worked out, and the figure shown is the one that
            // would be stored. To the cent, because it is here to be held
            // against a contract note and "€300" beside 307.42 reads as
            // agreement. Across two currencies there is no figure to show —
            // that sum takes the rate of the entry's own day — so the box says
            // which currency it wants instead.
            placeholder={
              acrossCurrencies
                ? `${kind === "buy" ? "Debited" : "Credited"} in ${currency || "…"}`
                : `${money(currency, "cents").format(derived)} if left blank`
            }
            title="What the account actually moved by, from your statement. Leave it blank and it is worked out from the quantity, the price and the fees (across two currencies, at the ECB rate of the date above, where your broker's rate will differ a little)."
            value={debit}
            onChange={(e) => setDebit(e.target.value)}
          />
        )}
        <button className={btnClass} disabled={submitting}>
          {/* The label reads the KIND rather than naming one. It used to say
              "Add buy" for every kind but `close`, so a dividend was recorded
              by pressing a button that said you were buying — the one moment
              the form states what it is about to do, and it said the wrong
              thing for two of its four kinds. Reading `kind` also means a
              fifth one cannot inherit the wrong word. */}
          {submitting ? "..." : editId != null ? "Save" : isClose ? "Record disposal" : `Add ${kind}`}
        </button>
        {editId != null && (
          <button type="button" onClick={reset} className="rounded-sm px-3 py-2 text-sm text-ink-soft hover:text-ink">
            Cancel
          </button>
        )}
      </form>
      {/* Outside the form element on purpose: a form cannot nest, and this is
          its own small act — one field, or two if the reader wants to say what
          kind of place it is. Enter commits it rather than the buy above. */}
      {addingInstitution && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-sm border border-rule bg-tint p-2">
          <input
            ref={newNameRef}
            className={inputClass}
            placeholder="Name of the bank or broker"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void createAndSelect();
              }
            }}
          />
          <input
            className={inputClass + " w-32"}
            placeholder="Type (optional)"
            value={newType}
            onChange={(e) => setNewType(e.target.value)}
          />
          <button
            type="button"
            className={btnClass}
            disabled={creatingInstitution || !newName.trim()}
            onClick={() => void createAndSelect()}
          >
            {creatingInstitution ? "..." : "Add and use"}
          </button>
          <button
            type="button"
            onClick={() => setAddingInstitution(false)}
            className="rounded-sm px-3 py-2 text-sm text-ink-soft hover:text-ink"
          >
            Cancel
          </button>
          <span className="text-xs text-ink-faint">
            It joins the list in Records → Wealth, where you can give it a cash
            balance and its situations.
          </span>
        </div>
      )}
      {/* Shown, and then allowed through. The records being behind is the case
          the reader is here to correct, so this is a fact about the records,
          not a verdict on the entry. */}
      {overspend && (
        <p className="mt-2 text-xs text-warn">
          That is more than the {money(overspend.base_currency, "cents").format(overspend.projected)} on record at{" "}
          {overspend.institution_name}. It was recorded anyway. If the balance is
          simply behind, its cash anchor in Records → Wealth is where you say so.
        </p>
      )}
      {pickNote && <p className="mb-2 text-xs text-olive">{pickNote}</p>}
      {error && <p className="text-down">{error}</p>}
      {priceNote && <p className="text-xs text-up">{priceNote}</p>}
      <RowsOrEmpty loading={false} error={null} empty={items.length === 0} emptyText="No transactions yet. Add one, or let PACs and dividends auto-record at app start.">
        {items.map((t) => (
          <Row
            key={t.id}
            onEdit={() => startEdit(t)}
            onDelete={() => remove(t)}
            title={t.asset_name}
            badge={[t.plan_id != null ? "PAC" : t.kind, t.estimated ? "est." : null]
              .filter(Boolean)
              .join(" · ")}
            subtitle={[
              fmtDate(t.date),
              t.price_currency ? `${t.quantity} × ${money(t.price_currency).format(t.unit_price)}` : null,
              t.fees ? `fees ${money(t.currency).format(t.fees)}` : null,
              // A sum fixed at one day's rate says which day, so it can be held
              // against the statement.
              t.fx_as_of ? `at the ECB rate of ${fmtDate(t.fx_as_of)}` : null,
              instName(t.institution_id),
              t.symbol,
            ]
              .filter(Boolean)
              .join(" · ")}
            detail={t.currency_note ? `⚠ ${t.currency_note}` : undefined}
            note={t.note}
            value={(t.kind === "buy" ? "−" : "+") + money(t.currency).format(t.amount)}
          />
        ))}
      </RowsOrEmpty>
    </Section>
    </div>
  );
}
