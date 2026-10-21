/* The day each questionnaire answer was recorded, as the Profile shows it.

   Since brief AC the confidant, the synthesis, the chat and the MCP server
   read every answer with the day it was recorded, in brackets in front of it
   (`advisor.ANSWER_DAYS`): what was true for the reader then. The Profile
   showed no day at all, "Other answers" included, so the reader could not
   see what the models are told about when they said something (measured at
   `c61e5bc`, brief BE). The day is the reader's own day of `created_at`, as
   the backend's `dated.local_day` writes it for the models. */

import { localDay } from "./calendarDays.ts";

/** A stored answer, as `GET /api/survey` returns it. */
export type StoredAnswer = { question_key: string; answer?: string | null; created_at: string };

/** Each stored answer's words and day, by its question. */
export type Recorded = Record<string, { answer: string; day: string }>;

/** What `answerDays` keeps of the stored answers: one with no words has no day
    to show. */
export function answerDays(stored: StoredAnswer[]): Recorded {
  const out: Recorded = {};
  for (const a of stored) {
    if (a.answer == null || a.answer.trim() === "") continue;
    const at = new Date(a.created_at);
    if (Number.isNaN(at.getTime())) continue;
    out[a.question_key] = { answer: a.answer, day: localDay(at) };
  }
  return out;
}

/** The faint line under an answer, while its box shows the answer as stored:
    an answer typed over it is not the one recorded that day, and its own day
    is the day it is saved. */
export function recordedLine(recorded: Recorded, key: string, shown: string): string | null {
  const stored = recorded[key];
  return stored && stored.answer === shown ? `Recorded on ${stored.day}.` : null;
}
