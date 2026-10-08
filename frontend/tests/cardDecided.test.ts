/* A decided card, put where the panel shows it.

   Brief AJ: the server sends the card as stored the moment a decision is on
   record (`decided`), before the reply that follows, and the panel swaps it
   in at once. On 2026-10-08 the reader's second card kept its buttons after
   its decision because the panel redrew cards only after a reply ended well.

   Run by `npm test` with Node's own test runner. Type-checked by `tsc -b`
   through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import type { ChatBlock, ChatCardBlock } from "../src/api/chat.ts";
import { withDecided } from "../src/components/cardDecided.ts";

function card(id: string, outcome: "pending" | "confirmed" | "rejected"): ChatCardBlock {
  return {
    kind: "card",
    card_id: id,
    call_id: `call_${id}`,
    tool: "suggest_instrument",
    title: `watch: Example fund ${id}`,
    outcome,
    result: outcome === "confirmed" ? { name: `Example fund ${id}` } : null,
  };
}

type Message = { id: string; blocks: ChatBlock[] };

const ANSWER: Message = {
  id: "m2",
  blocks: [{ kind: "text", text: "Due da guardare." }, card("a", "pending"), card("b", "pending")],
};
const QUESTION: Message = { id: "m1", blocks: [{ kind: "text", text: "Due fondi?" }] };

test("the decided card replaces the one shown, in place, and nothing else moves", () => {
  const after = withDecided([QUESTION, ANSWER], card("b", "confirmed"));

  assert.deepEqual(after, [
    QUESTION,
    {
      id: "m2",
      blocks: [{ kind: "text", text: "Due da guardare." }, card("a", "pending"), card("b", "confirmed")],
    },
  ]);
  assert.equal(after[0], QUESTION, "a message without the card is the same object");
  assert.deepEqual(ANSWER.blocks[2], card("b", "pending"), "the messages given are not changed");
});

test("a rejection is put in place the same way", () => {
  const after = withDecided([ANSWER], card("a", "rejected"));
  assert.equal((after[0].blocks[1] as ChatCardBlock).outcome, "rejected");
  assert.equal((after[0].blocks[2] as ChatCardBlock).outcome, "pending");
});

test("a card the panel does not hold changes nothing", () => {
  const messages = [QUESTION, ANSWER];
  assert.equal(withDecided(messages, card("z", "confirmed")), messages);
});
