import { api } from "./client";
import type { Schemas } from "./types";

export type ChatModels = Schemas["ChatModelsRead"];
// What a message is made of: blocks with a `kind`. Text, thought, and the
// tools consulted between them; a card later is a new member here, and the
// panel learns to render it. Widening this is not optional busywork — it is
// the one place the compiler catches a backend that grew a kind, because
// `ChatMessageRead.blocks` is generated and assigning the wider array to the
// narrower one fails to build.
export type ChatBlock =
  | Schemas["ChatTextBlock"]
  | Schemas["ChatThoughtBlock"]
  | Schemas["ChatPageBlock"]
  | Schemas["ChatToolBlock"]
  | Schemas["ChatSourcesBlock"]
  | Schemas["ChatCardBlock"];
// Named on its own because the panel renders it with a component of its own;
// still the generated shape, so it cannot drift from the block the backend
// stores.
export type ChatToolBlock = Schemas["ChatToolBlock"];
export type ChatSourcesBlock = Schemas["ChatSourcesBlock"];
export type ChatCardBlock = Schemas["ChatCardBlock"];
export type ChatPageBlock = Schemas["ChatPageBlock"];
// Where the reader is when a question is sent: one kind per level a question
// can be about. Ids, because they come from the app's own state; the server
// turns them into the names a model reads, and into the label it stores.
export type ChatPage = NonNullable<Schemas["ChatRequest"]["page"]>;
export type ChatMessage = Schemas["ChatMessageRead"];
export type ChatConversation = Schemas["ChatConversationRead"];
export type ChatConversationDetail = Schemas["ChatConversationDetail"];
// The frames the stream carries, discriminated on `kind` — the backend's own
// shapes. This list is written by hand, so adding a member to it is what makes
// the switch below fail to compile; the `never` at the end of that switch is
// what turns "a kind nobody handled" into a build error instead of a frame
// dropped in silence, which is what happened before it was there.
export type ChatEvent =
  | Schemas["ChatStart"]
  | Schemas["ChatThought"]
  | Schemas["ChatDelta"]
  | Schemas["ChatTool"]
  | Schemas["ChatSources"]
  | Schemas["ChatStep"]
  | Schemas["ChatCard"]
  | Schemas["ChatDecided"]
  | Schemas["ChatDone"]
  | Schemas["ChatError"];
// A step of a long tool, arriving while it runs. Not a block: nothing stores
// it, because the run it reports is itself a record and the card that proposed
// it becomes the receipt.
export type ChatStepEvent = Schemas["ChatStep"];

// GET /api/chat/models — the dropdown, default first.
export async function getChatModels(): Promise<ChatModels> {
  return (await api.get<ChatModels>("/api/chat/models")).data;
}

// GET /api/chat/conversations — the history, most recently spoken to first.
export async function listConversations(): Promise<ChatConversation[]> {
  return (await api.get<ChatConversation[]>("/api/chat/conversations")).data;
}

// GET /api/chat/conversations/{id} — one conversation with every turn.
export async function getConversation(id: number): Promise<ChatConversationDetail> {
  return (await api.get<ChatConversationDetail>(`/api/chat/conversations/${id}`)).data;
}

// DELETE /api/chat/conversations/{id}
export async function deleteConversation(id: number): Promise<void> {
  await api.delete(`/api/chat/conversations/${id}`);
}

/* How a stream ended. Three outcomes, not two: the backend sends `done` when
   the answer is complete and `error` when it cannot continue, and a connection
   that closes with neither is a BREAK — the model was cut off, or the server
   went away mid-sentence. From the bytes alone a break looks like a short
   answer, which is why the distinction has to be made here and shown to the
   reader, not inferred from the text stopping. `aborted` is the reader's own
   Stop, which the server records as cut — it cannot tell the two apart. */
export type StreamEnd =
  | { kind: "done"; model: string; messageId: number }
  | { kind: "error"; detail: string }
  | { kind: "cut" }
  | { kind: "aborted" };

// POST /api/chat — one more question, answered as server-sent events. The
// server holds the conversation; `conversationId` null opens a new one and the
// `start` frame says which.
//
// `fetch`, not axios and not EventSource: EventSource can only GET, and the
// question travels in the body; axios buffers the response. `signal` aborts
// the request, which closes the connection, which is what stops the model on
// the far side — an abandoned answer must not keep billing.
export async function streamChat(
  body: {
    conversation_id: number | null;
    content: string;
    model: string | null;
    page: ChatPage | null;
  },
  handlers: StreamHandlers,
  signal: AbortSignal,
): Promise<StreamEnd> {
  return post("/api/chat", body, handlers, signal);
}

/* What a streamed turn can report while it is running. `onCard` is the one
   that ends a turn rather than continuing it: the model proposed a write, the
   card says what it would do, and nothing else arrives until the reader
   answers it through `decideCard`. `onStep` is the opposite end of the same
   exchange: the reader confirmed the analyzer's card, and the minute it takes
   arrives as its finished steps before a word of the answer does. */
export type StreamHandlers = {
  /** `pageLabel` is where the question was stored as asked from, resolved by
      the server; null when it was sent without a page, or answers a card. */
  onStart: (conversationId: number, userMessageId: number | null, pageLabel: string | null) => void;
  /** A piece of the model's reasoning — arrives before the answer, for seconds. */
  onThought: (text: string) => void;
  /** A piece of the answer itself. */
  onDelta: (text: string) => void;
  /** A tool the model asked for, named, once it has been answered, with the
      reason when it failed (null otherwise, which claims no success). */
  onTool: (name: string, detail: string | null) => void;
  /** What a web search found, whole, as the search the app ran comes back:
      the query it sent and the pages, under the search's line and before the
      words written from them. */
  onSources: (found: { query: string; pages: { url: string; title: string }[] }) => void;
  /** One finished step of a long tool. The analyzer is three to six model
      calls; this is what the minute is made of. */
  onStep: (step: ChatStepEvent) => void;
  /** A write the model proposed. Nothing has happened yet. */
  onCard: (card: ChatCardBlock) => void;
  /** A card the reader decided, as the server now stores it: sent the moment
      the decision is on record, before the reply that follows it, so the card
      reads as decided however that reply ends. */
  onDecided: (card: ChatCardBlock) => void;
};

// POST /api/chat/cards/{id} — confirm or reject one proposed write, and hear
// what the model makes of it. The write runs before the first byte, so a
// stream that starts at all is a decision already taken, and its first frame
// after `start` is the card as stored (`decided`); a refusal (the card is
// gone, already answered, or stale) arrives as an HTTP error instead.
//
// One exception, and it is the analyzer: three to six model calls, a minute of
// them, and a minute of a request holding open before the first byte is the
// spinner the step events exist to replace. Its decision is still taken before
// the stream — nothing else can decide that card — and its WORK happens on it,
// which is why a failure there arrives as an `error` event rather than a 409.
//
// A second endpoint and not a frame down the first one, because SSE only goes
// one way: the answer to a card cannot travel up the pipe that proposed it.
export async function decideCard(
  cardId: string,
  body: { decision: "confirm" | "reject"; model: string | null },
  handlers: StreamHandlers,
  signal: AbortSignal,
): Promise<StreamEnd> {
  return post(`/api/chat/cards/${encodeURIComponent(cardId)}`, body, handlers, signal);
}

// The one reader both of them use. Asking a question and answering a card
// differ in the URL and the body and in nothing else — same frames, same four
// endings, same rule that a stream ending without `done` or `error` was cut.
async function post(
  url: string,
  body: unknown,
  handlers: StreamHandlers,
  signal: AbortSignal,
): Promise<StreamEnd> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    if (signal.aborted) return { kind: "aborted" };
    return { kind: "error", detail: "The backend did not answer. Is it running on :8000?" };
  }
  if (!response.ok || !response.body) {
    // A 404, 422 or 500 before any frame was sent: FastAPI's `detail` when it
    // wrote one, the status otherwise.
    let detail = `The backend refused the question (HTTP ${response.status}).`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string" && data.detail.trim()) detail = data.detail.trim();
    } catch {
      /* not JSON — keep the status line */
    }
    return { kind: "error", detail };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Frames end in a blank line. Whatever follows the last one is a frame
      // still arriving and stays in the buffer.
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const event = parseFrame(frame);
        if (!event) continue;
        switch (event.kind) {
          case "start":
            // A field with a default is optional in the generated type, and
            // "absent" and "null" mean the same thing here: nobody asked a
            // question, because this turn is the answer to a card.
            handlers.onStart(
              event.conversation_id,
              event.user_message_id ?? null,
              event.page_label ?? null,
            );
            break;
          case "thought":
            handlers.onThought(event.text);
            break;
          case "delta":
            handlers.onDelta(event.text);
            break;
          case "tool":
            handlers.onTool(event.name, event.detail ?? null);
            break;
          case "sources":
            handlers.onSources({ query: event.query, pages: event.pages });
            break;
          case "step":
            handlers.onStep(event);
            break;
          case "card":
            handlers.onCard(event.card);
            break;
          case "decided":
            handlers.onDecided(event.card);
            break;
          case "done":
            return { kind: "done", model: event.model, messageId: event.message_id };
          case "error":
            return { kind: "error", detail: event.detail };
          default: {
            // Exhaustiveness. A kind added to ChatEvent and handled nowhere
            // stops being assignable to never, and this line stops compiling —
            // which is the whole point: an unhandled frame is otherwise
            // dropped here without a word, and the reader sees a pause with no
            // cause. `tsc` is the only test the frontend has.
            const unhandled: never = event;
            void unhandled;
          }
        }
      }
    }
  } catch {
    if (signal.aborted) return { kind: "aborted" };
    return { kind: "cut" };
  }
  // The connection closed without a `done` or an `error`: the answer broke off.
  return { kind: "cut" };
}

// One SSE frame -> the event on its data line, or null for anything that is
// not ours (a comment, a keep-alive). The `event:` line is a routing hint that
// repeats `kind`; the JSON is what we trust.
function parseFrame(frame: string): ChatEvent | null {
  const data = frame
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    return JSON.parse(data) as ChatEvent;
  } catch {
    return null;
  }
}
