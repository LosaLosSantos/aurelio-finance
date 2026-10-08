/* A decided card, put where the reader sees it.

   The server sends the card as it stored it the moment the decision is on
   record (the `decided` event), before the reply that follows. This puts it
   in place of the card the panel was showing, in whichever message holds it,
   so the card reads as decided whatever that reply does: on 2026-10-08 the
   reader's second confirmation was stored, its reply failed, and the card
   kept its buttons, because the panel only redrew cards once a reply ended
   well.

   No runtime imports, so `npm test` reaches it. */

import type { ChatBlock, ChatCardBlock } from "../api/chat";

/** `messages` with the card whose id is `card.card_id` replaced by `card`;
    the same array, untouched, when no message holds that card. */
export function withDecided<M extends { blocks: ChatBlock[] }>(
  messages: M[],
  card: ChatCardBlock,
): M[] {
  let found = false;
  const next = messages.map((m) => {
    if (!m.blocks.some((b) => b.kind === "card" && b.card_id === card.card_id)) return m;
    found = true;
    return {
      ...m,
      blocks: m.blocks.map((b) => (b.kind === "card" && b.card_id === card.card_id ? card : b)),
    };
  });
  return found ? next : messages;
}
