import { useState } from "react";
import {
  acceptAllPaid,
  acceptPaid,
  declinePaid,
  type PaidProposal,
  type UnreadPurchases,
} from "../api/portfolio";
import {
  NOTICE_NOTE,
  NOTICE_TITLE,
  acceptAllLabel,
  entryLine,
  proposalLine,
  unreadLine,
  type Formats,
} from "./paidRecovery";
import { apiError, btnClass, locale, money } from "./ui";

/* What the ledger paid before an account's latest situation, proposed row by
   row above the table whose shares it changes (brief AW; the reader chose the
   Portfolio, 2026-10-15). The sentences are `paidRecovery.ts`'s; this places
   them, sends a press and has the page read itself again, so the row's share
   ("23% paid") reads back what was just written. */

const keepClass =
  "rounded-sm border border-olive px-2 py-1 text-xs font-medium text-olive transition hover:bg-olive/5 disabled:opacity-50";
const noClass =
  "rounded-sm border border-rule px-2 py-1 text-xs text-ink-soft transition hover:border-olive hover:text-olive disabled:opacity-50";

export function PaidRecoveryNotice({
  proposals,
  unread,
  baseCurrency,
  onChanged,
}: {
  proposals: PaidProposal[];
  unread: UnreadPurchases[];
  /** The currency the figures are in: the base of the payload they came in. */
  baseCurrency: string;
  /** Called after a press the backend took: the page reads itself again. */
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (proposals.length === 0 && unread.length === 0) return null;

  const formats: Formats = {
    money: (amount) => money(baseCurrency).format(amount),
    day: (iso) =>
      new Date(iso + "T00:00:00").toLocaleDateString(locale, {
        day: "numeric",
        month: "short",
        year: "numeric",
      }),
    units: (n) => n.toLocaleString(locale, { maximumFractionDigits: 6 }),
  };

  async function press(send: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await send();
      onChanged();
    } catch (err) {
      setError(apiError(err, "The backend did not take that. Is it running on :8000?"));
    } finally {
      setBusy(false);
    }
  }

  const all = acceptAllLabel(proposals.length);
  return (
    <div className="space-y-2">
      {proposals.length > 0 && (
        <div className="border-l-2 border-olive bg-olive/5 px-3 py-2 text-xs text-ink-soft">
          <div className="font-semibold text-ink">{NOTICE_TITLE}</div>
          <p className="mt-0.5">{NOTICE_NOTE}</p>
          <ul className="mt-2 space-y-3">
            {proposals.map((p) => (
              <li key={p.holding_id}>
                <p className="text-ink">{proposalLine(p, formats)}</p>
                {p.entries.length > 0 && (
                  <ul className="mt-0.5 text-ink-faint">
                    {p.entries.map((e, i) => (
                      <li key={i}>{entryLine(e, formats)}</li>
                    ))}
                  </ul>
                )}
                <div className="mt-1 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => press(() => acceptPaid(p))}
                    aria-label={`Keep as paid: ${p.asset_name}`}
                    className={keepClass}
                  >
                    Keep as paid
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => press(() => declinePaid(p))}
                    aria-label={`No, leave ${p.asset_name} as it is`}
                    className={noClass}
                  >
                    No
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {all && (
            <button
              type="button"
              disabled={busy}
              onClick={() => press(() => acceptAllPaid(proposals))}
              className={btnClass + " mt-3"}
            >
              {all}
            </button>
          )}
        </div>
      )}
      {unread.length > 0 && (
        <div className="space-y-1 border-l-2 border-warn bg-warn-tint px-3 py-2 text-xs text-warn">
          {unread.map((u) => (
            <p key={u.holding_id}>{unreadLine(u, formats)}</p>
          ))}
        </div>
      )}
      {error && <p className="text-xs text-down">{error}</p>}
    </div>
  );
}
