/* The chat's Thinking control (briefs BF and BH), as the reader reads it.

   Beside the model menu: "normal", what the model does when nothing is said,
   the one lighter position the model has, "light" where it reasons less and
   "off" where it stops, and on Opus 5.5 two positions above normal, "high"
   and "max" (brief BH). The backend's menu says which, in the control's order
   (`ChatModel.thinking.positions`, from `chat.THINKING` and `chat.HEAVY`),
   what was measured of them, and the line the panel shows under the control
   while high or max is chosen; a model with none (Sonnet 4.6, whose normal is
   already off, or a model set only in backend/.env) shows no control.

   The reader's choice is kept per model in the tab, beside the model pick,
   and sent with every question and every card's answer. "normal" is sent as
   nothing, so the request is the one it was before the control.

   Its one runtime import names `.ts`, so `npm test` reaches it. */

import type { Schemas } from "../api/types";
import { modelName } from "./modelMenu.ts";

type Menu = Schemas["ChatModelsRead"];

/** A position of the control. */
export type Position = "normal" | "light" | "off" | "high" | "max";

/** A position that is sent, every one but normal. */
export type Chosen = Exclude<Position, "normal">;

/** The choices kept in the tab, by model slug. Normal is the absence of an
    entry, so a model never touched reads normal. */
export type Choices = Record<string, Chosen>;

const CHOSEN: readonly Chosen[] = ["light", "off", "high", "max"];

function thinkingOf(slug: string, menu: Menu | null) {
  return menu?.models.find((m) => m.slug === slug)?.thinking ?? null;
}

/** Every position `slug` offers, normal among them, in the control's order;
    null when it offers none or the menu has not loaded. */
export function positionsOf(slug: string, menu: Menu | null): Position[] | null {
  return thinkingOf(slug, menu)?.positions ?? null;
}

/** The position the control shows for `slug`: the kept choice while the model
    still offers it, normal otherwise. */
export function positionOf(choices: Choices, slug: string, menu: Menu | null): Position {
  const kept = choices[slug];
  return kept && (positionsOf(slug, menu) ?? []).includes(kept) ? kept : "normal";
}

/** What a question or a card's answer is sent with: the chosen word, null for
    normal. Before the menu has loaded nothing is known, and the kept choice
    goes as it is, as the model pick does; the backend refuses a position its
    model does not have. */
export function thinkingToSend(choices: Choices, slug: string, menu: Menu | null): Chosen | null {
  if (menu === null) return choices[slug] ?? null;
  const position = positionOf(choices, slug, menu);
  return position === "normal" ? null : position;
}

/** `choices` with `slug` set to `position`: normal removes its entry. */
export function withPosition(choices: Choices, slug: string, position: Position): Choices {
  const next: Choices = { ...choices };
  if (position === "normal") delete next[slug];
  else next[slug] = position;
  return next;
}

/** The words a position is shown with. */
export function positionLabel(position: Position): string {
  return `Thinking: ${position}`;
}

/** The line the panel shows under the control while `position` is chosen for
    `slug`, or null: only high and max have one. */
export function lineOf(slug: string, position: Position, menu: Menu | null): string | null {
  return thinkingOf(slug, menu)?.lines[position] ?? null;
}

// What each position asks of the model, as the "?" says it.
const ASKS: Record<Chosen, string> = {
  light: "to reason less",
  off: "not to reason",
  high: "to reason more",
  max: "to reason the most",
};

/* OpenRouter's page on streaming (read 2026-10-27): "For supported providers,
   this immediately stops model processing and billing"; Amazon Bedrock and
   Google are listed as not supported. Said where a turn may think for
   minutes. */
const STOP = "A Stop ends what you see; OpenRouter stops the model and its billing only on the providers that support it.";

/** What the panel's "?" says of the control for `slug`, or null when the
    model offers none: what the positions mean, then what was measured. A
    model with positions above normal says them all, and the Stop. */
export function thinkingHelp(slug: string, menu: Menu | null): string | null {
  const thinking = thinkingOf(slug, menu);
  if (!thinking) return null;
  const name = modelName(slug);
  if (thinking.heavier_measured === null) {
    return (
      `Thinking: normal is what ${name} does when nothing is said, and ${thinking.lighter} ` +
      `asks it ${ASKS[thinking.lighter]}. Measured on one look-through question (Oct 22, 2026), ` +
      `every setting found the same thing; ${thinking.measured}.`
    );
  }
  // "light asks it to reason less, high to reason more, and max to reason the most"
  const said = thinking.positions
    .filter((p): p is Chosen => p !== "normal")
    .map((p, i) => (i === 0 ? `${p} asks it ${ASKS[p]}` : `${p} ${ASKS[p]}`));
  const listed = `${said.slice(0, -1).join(", ")}, and ${said[said.length - 1]}`;
  return (
    `Thinking: normal is what ${name} does when nothing is said; ${listed}. ` +
    `Measured on one look-through question (Oct 22, 2026), ${thinking.lighter} found what normal ` +
    `found; ${thinking.measured}. ${thinking.heavier_measured} ${STOP}`
  );
}

/** The choices read back from the tab: only entries that are a slug and a
    word that can be sent survive, whatever was stored. */
export function readChoices(raw: unknown): Choices {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Choices = {};
  for (const [slug, word] of Object.entries(raw as Record<string, unknown>)) {
    if (CHOSEN.includes(word as Chosen)) out[slug] = word as Chosen;
  }
  return out;
}
