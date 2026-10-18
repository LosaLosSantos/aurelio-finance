/* The chat's menu of models, as the reader reads it (brief BB).

   Each entry carries what today's read of OpenRouter's public list says of it
   (`model_list` on the backend): the day after which the model may be removed
   (`retires`), and whether the list has it at all (`listed`, null when the
   list has not been read today). The menu says either beside the name from the
   first day the list says it. Nothing leaves the menu on the list's say-so: a
   name that had left the list was seen still answering (2026-09-24), so it
   stays, marked. Above the question box the panel says the backend's
   sentence for the model a question would call, with where it is set.

   No runtime imports, so `npm test` reaches it. */

import type { Schemas } from "../api/types";

type Menu = Schemas["ChatModelsRead"];
type Entry = Schemas["ChatModel"];

/** A model's name without its provider, as the select and the "?" say it. */
export function modelName(slug: string): string {
  return slug.includes("/") ? slug.slice(slug.indexOf("/") + 1) : slug;
}

/** One option of the menu: the name, "default" on the one that answers when
    nothing is picked, and what the list says of it. */
export function optionLabel(entry: Entry, isDefault: boolean): string {
  const said = [modelName(entry.slug)];
  if (isDefault) said.push("default");
  if (entry.listed === false) said.push("no longer listed by OpenRouter");
  else if (entry.retires) said.push(`may be retired after ${entry.retires}`);
  return said.join(" · ");
}

/** What the panel's "?" says of the models: each with what is known of it,
    then a sentence for each one the list dates or no longer has. */
export function modelsHelp(menu: Menu): string {
  const known = menu.models.map((m) => `${modelName(m.slug)}, ${m.note}`).join("; ");
  const listSays = menu.models.flatMap((m) => {
    if (m.listed === false) return [`OpenRouter no longer lists ${modelName(m.slug)}.`];
    if (m.retires) return [`OpenRouter may retire ${modelName(m.slug)} after ${m.retires}.`];
    return [];
  });
  return [`The models: ${known}.`, ...listSays].join(" ");
}

/** What the panel says above the question box of the models the next question
    would call: the `current` model's own warning, and the web search's when
    that model searches. Each is the backend's sentence, written only when
    OpenRouter's list dates the model within its days, has passed its day, or
    no longer has it; empty otherwise, and before the menu has loaded. */
export function modelNotices(current: string, menu: Menu | null): string[] {
  const entry = menu?.models.find((m) => m.slug === current);
  if (!menu || !entry) return [];
  const said = [entry.warning, entry.searches ? menu.search_warning : null];
  return said.filter((s): s is string => Boolean(s));
}

/** The model a question is sent with: the reader's pick while the menu offers
    it, else null, which the backend answers with the default. A pick kept in
    the tab from before the menu changed (a model dropped from backend/.env,
    one the app no longer offers) is not sent, so what goes out is what the
    select shows. Before the menu has loaded nothing is known, and the pick
    goes as it is. */
export function pickToSend(pick: string | null, menu: Menu | null): string | null {
  if (pick === null || menu === null) return pick;
  return menu.models.some((m) => m.slug === pick) ? pick : null;
}
