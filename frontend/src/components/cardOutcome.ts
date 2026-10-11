/* What a card in the chat says it is, by what became of it.

   Four outcomes since brief AN (2026-10-10). A card refused at its
   confirmation because what it was drawn against had changed is stored as
   stale: nothing was written, it cannot be decided again, and the chat draws a
   fresh one when the reader still wants the change. Until then the refusal
   was stored nowhere, and the card kept offering a button that could only be
   refused again.

   Pure, so `tests/cardOutcome.test.ts` runs it under Node without a bundler. */

export type Outcome = "pending" | "confirmed" | "rejected" | "stale";

/** Whether the card still waits for the reader's decision. */
export function waiting(outcome: Outcome | undefined): boolean {
  return (outcome ?? "pending") === "pending";
}

/** The word over the card: proposed, what a confirmed one is now (`done`,
    the tool's own word), rejected, or out of date. */
export function heading(outcome: Outcome | undefined, done?: string | null): string {
  switch (outcome ?? "pending") {
    case "confirmed":
      return done || "Recorded";
    case "rejected":
      return "Rejected";
    case "stale":
      return "Out of date";
    default:
      return "Proposed";
  }
}

/** Said under a stale card's title. */
export const STALE_LINE =
  "What this card was drawn against changed before it was confirmed, so nothing was written. Ask again for a fresh one.";
