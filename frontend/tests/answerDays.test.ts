import { afterEach, test } from "node:test";
import assert from "node:assert/strict";

import { answerDays, recordedLine } from "../src/components/answerDays.ts";

const ZONE = process.env.TZ;
afterEach(() => {
  process.env.TZ = ZONE;
});

test("an answer's day is the reader's own day of when it was recorded", () => {
  process.env.TZ = "Europe/Rome";
  const days = answerDays([
    { question_key: "about_country", answer: "Somewhere", created_at: "2026-10-02T22:30:00+00:00" },
  ]);
  assert.deepEqual(days, { about_country: { answer: "Somewhere", day: "2026-10-03" } });
});

test("on a clock in UTC the same instant is the day before", () => {
  process.env.TZ = "UTC";
  const days = answerDays([
    { question_key: "about_country", answer: "Somewhere", created_at: "2026-10-02T22:30:00+00:00" },
  ]);
  assert.equal(days.about_country.day, "2026-10-02");
});

test("an answer with no words, or no readable time, has no day", () => {
  process.env.TZ = "UTC";
  const days = answerDays([
    { question_key: "a", answer: "", created_at: "2026-10-02T10:00:00+00:00" },
    { question_key: "b", answer: null, created_at: "2026-10-02T10:00:00+00:00" },
    { question_key: "c", answer: "yes", created_at: "not a time" },
  ]);
  assert.deepEqual(days, {});
});

test("the line says the day while the box shows the answer as stored", () => {
  const recorded = { home_buy: { answer: "yes", day: "2026-09-20" } };
  assert.equal(recordedLine(recorded, "home_buy", "yes"), "Recorded on 2026-09-20.");
});

test("an answer typed over it, or none on record, has no line", () => {
  const recorded = { home_buy: { answer: "yes", day: "2026-09-20" } };
  assert.equal(recordedLine(recorded, "home_buy", "no"), null);
  assert.equal(recordedLine(recorded, "about_country", "Somewhere"), null);
});
