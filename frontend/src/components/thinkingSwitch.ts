/* The chat's Thinking control (brief BF), as the reader reads it.

   Beside the model menu, two positions: "normal", what the model does when
   nothing is said, and the one lighter position the model has, "light" where
   it reasons less and "off" where it stops. The backend's menu says which
   (`ChatModel.thinking`, from `chat.THINKING`) and what was measured of it; a
   model with none (Sonnet 4.6, whose normal is already off, or a model set
   only in backend/.env) shows no control.

   The reader's choice is kept per model in the tab, beside the model pick,
   and sent with every question and every card's answer. "normal" is sent as
   nothing, so the request is the one it was before the control.

   Its one runtime import names `.ts`, so `npm test` reaches it. */

import type { Schemas } from "../api/types";
import { modelName } from "./modelMenu.ts";

type Menu = Schemas["ChatModelsRead"];

/** A position of the control. */
export type Position = "normal" | "light" | "off";

/** A model's lighter position. */
export type Lighter = "light" | "off";

/** The choices kept in the tab, by model slug. Normal is the absence of an
    entry, so a model never touched reads normal. */
export type Choices = Record<string, Lighter>;

/** The lighter position `slug` offers, or null when it offers none or the
    menu has not loaded. */
export function lighterOf(slug: string, menu: Menu | null): Lighter | null {
  const entry = menu?.models.find((m) => m.slug === slug);
  return entry?.thinking?.lighter ?? null;
}

/** The position the control shows for `slug`: the kept choice while the model
    still offers it, normal otherwise. */
export function positionOf(choices: Choices, slug: string, menu: Menu | null): Position {
  const kept = choices[slug];
  return kept && kept === lighterOf(slug, menu) ? kept : "normal";
}

/** What a question or a card's answer is sent with: the model's lighter word
    when the reader chose it, null for normal. Before the menu has loaded
    nothing is known, and the kept choice goes as it is, as the model pick
    does; the backend refuses a position its model does not have. */
export function thinkingToSend(choices: Choices, slug: string, menu: Menu | null): Lighter | null {
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

/** What the panel's "?" says of the control for `slug`, or null when the
    model offers none: what the two positions mean, then what was measured. */
export function thinkingHelp(slug: string, menu: Menu | null): string | null {
  const entry = menu?.models.find((m) => m.slug === slug);
  const thinking = entry?.thinking;
  if (!thinking) return null;
  const asks = thinking.lighter === "off" ? "asks it not to reason" : "asks it to reason less";
  return (
    `Thinking: normal is what ${modelName(slug)} does when nothing is said, and ${thinking.lighter} ` +
    `${asks}. Measured on one look-through question (Oct 22, 2026), every setting found the same ` +
    `thing; ${thinking.measured}.`
  );
}

/** The choices read back from the tab: only entries that are a slug and a
    lighter word survive, whatever was stored. */
export function readChoices(raw: unknown): Choices {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Choices = {};
  for (const [slug, word] of Object.entries(raw as Record<string, unknown>)) {
    if (word === "light" || word === "off") out[slug] = word;
  }
  return out;
}
