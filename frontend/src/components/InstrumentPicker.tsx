import { useEffect, useRef, useState } from "react";
import {
  getCatalogueStatus,
  lookupSymbols,
  searchInstruments,
  type InstrumentMember,
  type InstrumentSearch,
  type SymbolLookup,
} from "../api/instruments";
import { catalogueNotice, type CatalogueState } from "./catalogueNotice";
import { inputClass, locale, policyWord } from "./ui";

/* The instrument name field, with the catalogue behind it.

   The reason this exists is not typos. Eight fields are typed by hand for every
   position, and the ones nobody fills switch features off in silence: a missing
   ISIN is what the look-through hands to the issuer, and a missing acc/dist is
   why a dividend-paying position collects nothing. Choosing fills them; typing
   never will.

   Three rules it must not break:

   - The twins travel together. An accumulating fund and its distributing
     sibling carry identical names and differ only in what they do with
     dividends, so showing one alone invites picking it without ever revealing
     there was a choice. They are always rendered as a pair under one heading.
   - The manual door stays open. Plenty of real instruments are in no catalogue
     — BTC-EUR, US-domiciled ETFs, unlisted funds — so whatever is typed is
     always usable as-is, and saying so is the last row of the list.
   - It fills identity, never a quotation. Name, ISIN and policy come from the
     pick; the TICKER and the CURRENCY do not, because the catalogue's are for
     a different listing (EUNL for iShares Core MSCI World, whatever listing
     is held; USD for one that quotes in EUR). */

/* What a pick IS, and where it came from.

   One callback, not one per lane, and every branch names its own source. The
   reason is the rule the rest of the app already keeps: nothing enters without
   its provenance — a cost is `estimated` or it is not, a value carries the day
   it was `observed_on`, a position is tracked or opaque. This was the one place
   that dropped it: the owned lane used to report itself as a live Yahoo result
   with the exchange nulled out, so the caller could not tell a symbol confirmed
   by the market from one confirmed by the fact that you already hold it — and
   said "on its exchange" to paper over the gap.

   The three sources are genuinely different claims, which is why they are three
   branches and not one shape with optional fields:

   - `catalogue` knows the IDENTITY (ISIN, acc/dist) and no quotation.
   - `live` knows a QUOTABLE symbol and no ISIN, because Yahoo has none.
   - `owned` knows a symbol that is right BY DEFINITION — it is the one already
     on your position — and needs no market round-trip to prove it. */
export type InstrumentChoice =
  | { source: "catalogue"; name: string; isin: string; distribution_policy: string | null }
  | {
      source: "live";
      name: string;
      symbol: string;
      exchange: string | null;
      quote_type: string | null;
    }
  | { source: "owned"; name: string; symbol: string; institution: string | null };

function detail(m: InstrumentMember): string {
  return [
    m.ter != null ? `TER ${m.ter}%` : null,
    m.size_meur ? `${m.size_meur.toLocaleString(locale)} M€` : null,
    m.domicile,
    m.base_ticker,
  ]
    .filter(Boolean)
    .join(" · ");
}

// The exchange codes worth spelling out: a reader knows NASDAQ, not NMS, and
// the exchange is the ONLY thing separating two rows with an identical name.
const EXCHANGES: Record<string, string> = {
  NMS: "NASDAQ", NGM: "NASDAQ", NCM: "NASDAQ", NYQ: "NYSE", PCX: "NYSE Arca",
  MIL: "Milan", GER: "Xetra", FRA: "Frankfurt", MUN: "Munich", STU: "Stuttgart",
  PAR: "Paris", AMS: "Amsterdam", EBS: "Zurich", LSE: "London", CCC: "crypto",
  CME: "CME", CMX: "COMEX", NYM: "NYMEX", TOR: "Toronto", HKG: "Hong Kong",
  CPH: "Copenhagen", SAO: "São Paulo", MEX: "Mexico", TLO: "Tel Aviv",
};

function exchangeName(code: string | null): string {
  if (!code) return "";
  return EXCHANGES[code] ?? code;
}

// Futures are the one type whose meaning EXPIRES: GC=F is "Gold Dec 26", a
// dated contract that rolls, so a position pinned to it measures something
// else in six months without saying so.
const EXPIRING = new Set(["future", "futures"]);

export function InstrumentPicker({
  value,
  onChange,
  onPick,
  owned,
  placeholder = "Name (type to search)",
  label = "Asset name",
  mark,
}: {
  value: string;
  onChange: (v: string) => void;
  /** Every lane reports here, and the branch says which one. Switch on
      `source` rather than sniffing which fields happen to be filled. */
  onPick: (choice: InstrumentChoice) => void;
  /** Positions already held. First lane where it exists, because a ledger
      entry usually adds to something you own, and a ticker that differs by one
      character silently starts a SECOND position for the same fund instead of
      adding to yours. Here the symbol is known-good by definition. */
  owned?: { symbol: string; name: string; institution?: string | null }[];
  placeholder?: string;
  /** What this box IS, as its programmatic name. The placeholder cannot do
      that job: it is the box's only name today, and it disappears the moment
      the reader types into it. Measured on the situation form, where nothing
      carries a `<label>` or an `aria-label` at all. */
  label?: string;
  /** Marks the box as needed (see required.ts): aria-required, and the
      question its empty box asks in place of the placeholder. */
  mark?: { "aria-required"?: true; placeholder?: string };
}) {
  const [result, setResult] = useState<InstrumentSearch | null>(null);
  const [live, setLive] = useState<SymbolLookup | null>(null);
  const [liveBusy, setLiveBusy] = useState(false);
  const [open, setOpen] = useState(false);
  // What the catalogue holds and where its download stands; null until asked.
  const [catalogue, setCatalogue] = useState<CatalogueState | null>(null);
  // Bumped when a download that was awaited arrives, so the words already
  // typed are searched again without anyone retyping them.
  const [arrived, setArrived] = useState(0);
  const rows = catalogue?.rows ?? null;
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void getCatalogueStatus()
      .then(setCatalogue)
      .catch(() => setCatalogue(null));
  }, []);

  // Debounced, but only as a courtesy to typing: the search is local and
  // answers in a couple of milliseconds, so there is no network to spare.
  useEffect(() => {
    if (value.trim().length < 2) {
      setResult(null);
      return;
    }
    const t = setTimeout(() => {
      // The two lanes are fetched INDEPENDENTLY and rendered as they arrive.
      // The catalogue answers from SQLite in milliseconds; the live lookup is
      // a network call. Awaiting them together would make the instant one wait
      // for the slow one, and would let an outage empty a list that had
      // perfectly good local results to show.
      void searchInstruments(value.trim())
        .then((r) => {
          setResult(r);
          setCatalogue({ rows: r.rows, state: r.state, retry_after: r.retry_after });
        })
        .catch(() => setResult(null));
      setLiveBusy(true);
      void lookupSymbols(value.trim())
        .then(setLive)
        .catch(() => setLive({ results: [], reachable: false }))
        .finally(() => setLiveBusy(false));
    }, 250);
    return () => clearTimeout(t);
  }, [value, arrived]);

  useEffect(() => {
    function away(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const families = result?.families ?? [];
  const showList = open && value.trim().length >= 2;
  const notice = catalogueNotice(catalogue, (iso) =>
    new Date(iso).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }),
  );

  // While the catalogue downloads, ask again every few seconds, so an open
  // list fills in by itself. Only then: the question is local and cheap, but a
  // list nobody is looking at has nothing to wait for.
  const waiting = showList && rows === 0 && catalogue?.state === "downloading";
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => {
      void getCatalogueStatus()
        .then((s) => {
          setCatalogue(s);
          if (s.rows > 0) setArrived((n) => n + 1);
        })
        .catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [waiting]);

  // Matched here rather than on the server: they are already in memory, and a
  // list of your own holdings should not wait on anything.
  const needle = value.trim().toLowerCase();
  const mine = (owned ?? []).filter(
    (o) =>
      o.name.toLowerCase().includes(needle) ||
      (o.symbol ?? "").toLowerCase().includes(needle),
  );

  return (
    <div ref={box} className="relative">
      <input
        className={inputClass + " w-72"}
        placeholder={placeholder}
        aria-label={label}
        {...mark}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {showList && (
        <div className="absolute left-0 top-full z-20 mt-1 max-h-96 w-[34rem] overflow-y-auto border border-rule bg-surface shadow-lg">
          {notice && (
            // Nothing to search yet: say where the download stands rather than
            // show an empty list that looks broken. No button: the app
            // downloads the catalogue by itself.
            <div role="status" className="px-3 py-2 text-xs text-ink-soft">
              {notice}
            </div>
          )}
          {mine.length > 0 && (
            <div className="flex items-baseline justify-between border-b border-rule bg-tint px-3 py-1.5">
              <span className="text-[0.6rem] font-semibold uppercase tracking-[0.12em] text-olive">
                Positions you already hold
              </span>
              <span className="text-[0.6rem] text-ink-faint">adds to them, not beside them</span>
            </div>
          )}
          {mine.map((o) => (
            <button
              type="button"
              key={o.symbol}
              onClick={() => {
                onPick({
                  source: "owned",
                  symbol: o.symbol,
                  name: o.name,
                  institution: o.institution ?? null,
                });
                setOpen(false);
              }}
              className="flex w-full items-baseline gap-2 border-b border-hair px-3 py-1.5 text-left hover:bg-tint"
            >
              <span className="w-24 shrink-0 truncate font-mono text-xs text-ink">{o.symbol}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-ink">{o.name}</span>
                {o.institution && (
                  <span className="block truncate text-[0.65rem] text-ink-soft">
                    held at {o.institution}
                  </span>
                )}
              </span>
            </button>
          ))}
          {(liveBusy || (live?.results.length ?? 0) > 0 || live?.reachable === false) && (
            <div className="flex items-baseline justify-between border-b border-rule bg-tint px-3 py-1.5">
              <span className="text-[0.6rem] font-semibold uppercase tracking-[0.12em] text-olive">
                Shares, ETFs &amp; crypto (live)
              </span>
              <span className="text-[0.6rem] text-ink-faint">
                {liveBusy ? "looking up…" : "the only source of a quotable symbol"}
              </span>
            </div>
          )}
          {live?.reachable === false && !liveBusy && (
            // "Nothing answered" is a different claim from "this does not
            // exist", and presenting the first as the second would teach
            // someone to correct a symbol that was right all along.
            <div
              className="border-b border-hair px-3 py-1.5 text-[0.65rem] text-warn"
              title="Nothing answered, which is a different claim from 'this instrument does not exist'. The catalogue lane below is local and unaffected."
            >
              Live source did not answer. This says nothing about the instrument.
            </div>
          )}
          {(live?.results ?? []).map((r) => {
            const expiring = EXPIRING.has((r.quote_type ?? "").toLowerCase());
            return (
              <button
                type="button"
                key={r.symbol}
                onClick={() => {
                  onPick({
                    source: "live",
                    symbol: r.symbol,
                    name: r.name ?? r.symbol,
                    exchange: r.exchange,
                    quote_type: r.quote_type,
                  });
                  setOpen(false);
                }}
                className="flex w-full items-baseline gap-2 border-b border-hair px-3 py-1.5 text-left hover:bg-tint"
              >
                <span className="w-24 shrink-0 truncate font-mono text-xs text-ink">
                  {r.symbol}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">{r.name ?? r.symbol}</span>
                  <span className="block truncate text-[0.65rem] text-ink-soft">
                    {r.quote_type}
                    {r.exchange && ` · ${exchangeName(r.exchange)}`}
                    {/* The price NEVER appears alone. The lookup returns no
                        currency, so two exchanges give two bare numbers in
                        different money — 38.60 and 33.60 for the same company,
                        which read as 15% apart and are equal. Naming the
                        exchange beside it is what stops the false comparison;
                        the currency itself arrives from the live check once
                        this row is chosen. */}
                    {r.price != null && ` · ${r.price} on ${exchangeName(r.exchange)}`}
                  </span>
                  {expiring && (
                    <span
                      className="block text-[0.6rem] text-warn"
                      title="A futures contract expires and rolls, so a position pinned to this symbol would measure a different contract in a few months without saying so."
                    >
                      ⚠ dated contract: expires and rolls
                    </span>
                  )}
                </span>
              </button>
            );
          })}
          {families.length > 0 && (
            // The catalogue holds UCITS FUNDS and nothing else, so searching a
            // share finds funds with that word in their name: an ETP on that
            // company, or a fund named after a different company that shares
            // a word with it. Naming the group is
            // what stops a plausible-looking row from being read as the thing
            // that was asked for. It is not hidden, it is placed.
            <div className="flex items-baseline justify-between border-b border-rule bg-tint px-3 py-1.5">
              <span className="text-[0.6rem] font-semibold uppercase tracking-[0.12em] text-olive">
                Funds &amp; ETFs (UCITS catalogue)
              </span>
              <span className="text-[0.6rem] text-ink-faint">
                shares and coins are not in here
              </span>
            </div>
          )}
          {result?.coverage === "partial" && families.length > 0 && (
            <div className="border-b border-hair px-3 py-1.5 text-[0.65rem] text-warn">
              Not every word matched. These are the closest, keep typing to narrow.
            </div>
          )}
          {families.map((f) => (
            <div key={f.key} className="border-b border-hair last:border-0">
              {f.members.map((m) => (
                <button
                  type="button"
                  key={m.isin}
                  onClick={() => {
                    onPick({
                      source: "catalogue",
                      name: m.name,
                      isin: m.isin,
                      distribution_policy: m.distribution_policy,
                    });
                    setOpen(false);
                  }}
                  className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left hover:bg-tint"
                >
                  {/* The policy leads the grey line rather than holding a column
                      of its own: the whole word needs 83px, and a column that
                      wide cut 1,034 of the catalogue's 4,544 names where this
                      layout cuts 231 (a 40px column of "Acc" cut 510). */}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink">{m.name}</span>
                    <span className="block truncate text-[0.65rem] text-ink-soft">
                      <span className={m.distribution_policy === "dist" ? "text-up" : undefined}>
                        {policyWord(m.distribution_policy) ?? "unknown"}
                      </span>
                      {" · "}
                      {m.isin} · {detail(m)}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ))}
          {rows !== 0 && families.length === 0 && (
            <div className="px-3 py-2 text-xs text-ink-soft">
              Nothing in the UCITS fund catalogue matches. For a share, a coin or a
              US-domiciled ETF that is the expected answer rather than a failure:
              type the name and the ticker yourself, and the live check below will
              confirm what it resolved to.
            </div>
          )}
          {/* Always last, always present: the catalogue covers UCITS funds and
              nothing else, so what you typed has to remain usable. */}
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="w-full border-t border-rule px-3 py-2 text-left text-xs text-ink-soft hover:bg-tint"
          >
            Use “<b className="text-ink">{value.trim()}</b>” as it is, with nothing from the
            catalogue attached
          </button>
        </div>
      )}
    </div>
  );
}
