import { test } from "node:test";
import assert from "node:assert/strict";

import type { Goal, GoalCreate } from "../src/api/goals.ts";
import {
  add,
  change,
  changeRef,
  counted,
  fromStored,
  goalBody,
  goalConflicts,
  keep,
  pending,
  refusedAt,
  remove,
  resolve,
  shownAs,
  writeOf,
  written,
  type GoalDraft,
} from "../src/components/goalDrafts.ts";

// The old rule: Goals.submit's body at a008d7f, copied verbatim with what it
// read (GOAL_TYPES, typeLabel, isTarget), so the one save sends what the
// goal's own button sent.
const GOAL_TYPES: { value: string; label: string }[] = [
  { value: "protect_inflation", label: "Protect from inflation" },
  { value: "stable_income", label: "Stable / passive income" },
  { value: "long_term_growth", label: "Long-term growth" },
  { value: "emergency_fund", label: "Emergency fund" },
  { value: "target_amount", label: "Target amount by a date" },
  { value: "other", label: "Something else (describe it)" },
];

function typeLabel(value: string | null): string | null {
  return GOAL_TYPES.find((t) => t.value === value)?.label ?? value;
}

function oldBody(name: string, type: string, currency: string, targetAmount: string, targetDate: string, currentAmount: string, monthly: string) {
  const isTarget = type === "target_amount";
  return {
    name: name.trim() || (typeLabel(type) ?? type),
    type,
    currency: currency.trim(),
    target_amount: isTarget && targetAmount ? Number(targetAmount) : null,
    target_date: isTarget && targetDate ? targetDate : null,
    current_amount: isTarget && currentAmount ? Number(currentAmount) : null,
    monthly_contribution: isTarget && monthly ? Number(monthly) : null,
  };
}

function goal(id: number, name: string, extra: Partial<Goal> = {}): Goal {
  return {
    id, name, type: "long_term_growth", currency: "EUR", target_amount: null, target_date: null,
    current_amount: null, monthly_contribution: null, notes: null, created_at: "2026-10-19T08:00:00+00:00", ...extra,
  };
}

const NEW: GoalCreate = {
  name: "A sabbatical", type: "target_amount", currency: "EUR", target_amount: 12000,
  target_date: "2029-06-30", current_amount: null, monthly_contribution: 300,
};

test("a goal's body is the one its own button sent, for every kind of goal and box", () => {
  const names = ["", "  ", "A sabbatical ", "Walk the Camino"];
  const amounts = ["", "0", "12000", "12000.5"];
  let cases = 0;
  for (const t of [...GOAL_TYPES.map((g) => g.value), "something_the_form_lacks"]) {
    for (const name of names) {
      for (const amount of amounts) {
        for (const date of ["", "2029-06-30"]) {
          for (const currency of ["EUR", " GBP ", "chf"]) {
            const form = { name, type: t, currency, targetAmount: amount, targetDate: date, currentAmount: amount, monthly: amount };
            assert.deepEqual(goalBody(form, typeLabel(t)), oldBody(name, t, currency, amount, date, amount, amount));
            cases += 1;
          }
        }
      }
    }
  }
  assert.equal(cases, 7 * 4 * 4 * 2 * 3);
});

test("a goal added, changed or deleted waits for the save, each said by its kind", () => {
  const stored = fromStored([goal(1, "Retire at 60"), goal(2, "Emergency fund", { type: "emergency_fund" })]);
  let d = add(stored, NEW);
  assert.deepEqual(d.map((x) => x.kind), ["kept", "kept", "added"]);
  d = change(d, 0, { ...shownAs(d[0]), name: "Retire at 58" });
  d = remove(d, 1);
  assert.deepEqual(d.map((x) => x.kind), ["changed", "deleted", "added"]);
  assert.equal(pending(d), 3);
  assert.equal(counted(d), 2);
  // A deleted one kept after all is as stored again; a new one deleted goes.
  d = keep(d, 1);
  d = remove(d, 2);
  assert.deepEqual(d.map((x) => x.kind), ["changed", "kept"]);
  assert.equal(pending(d), 1);
});

test("a new goal changed again stays new, and two new ones are told apart", () => {
  let d = add(add([], NEW), { ...NEW, name: "A second one" });
  assert.deepEqual(d.map((x) => x.ref), ["new:1", "new:2"]);
  d = change(d, 0, { ...NEW, monthly_contribution: 400 });
  assert.equal(d[0].kind, "added");
  assert.equal(shownAs(d[0]).monthly_contribution, 400);
});

test("the save sends the requests the goal's own buttons sent", () => {
  const g = goal(7, "Retire at 60");
  assert.deepEqual(writeOf({ kind: "added", ref: "new:1", now: NEW }), { method: "POST", body: NEW });
  assert.deepEqual(writeOf({ kind: "changed", ref: "id:7", goal: g, now: NEW }), { method: "PUT", id: 7, body: NEW });
  assert.deepEqual(writeOf({ kind: "deleted", ref: "id:7", goal: g }), { method: "DELETE", id: 7 });
  assert.equal(writeOf({ kind: "kept", ref: "id:7", goal: g }), null);
});

test("a goal changed or deleted on both sides is asked about; deleted on both sides, it is not", () => {
  const loaded = [goal(1, "Retire at 60"), goal(2, "A new car"), goal(3, "Emergency fund"), goal(4, "Untouched")];
  const drafts: GoalDraft[] = [
    { kind: "changed", ref: "id:1", goal: loaded[0], now: { ...loaded[0], name: "Retire at 58" } },
    { kind: "deleted", ref: "id:2", goal: loaded[1] },
    { kind: "changed", ref: "id:3", goal: loaded[2], now: { ...loaded[2], name: "Six months aside" } },
    { kind: "kept", ref: "id:4", goal: loaded[3] },
  ];
  // Elsewhere: 1 changed, 2 changed, 3 deleted, 4 changed (untouched here).
  const stored = [
    { ...loaded[0], target_amount: 500000 },
    { ...loaded[1], notes: "From the chat" },
    { ...loaded[3], name: "Changed by the chat" },
  ];
  assert.deepEqual(goalConflicts(drafts, stored), [
    { name: "Retire at 60", elsewhere: "changed", here: "changed" },
    { name: "A new car", elsewhere: "changed", here: "deleted" },
    { name: "Emergency fund", elsewhere: "deleted", here: "changed" },
  ]);
  assert.deepEqual(goalConflicts([{ kind: "deleted", ref: "id:2", goal: loaded[1] }], []), []);
});

test("laid over what is stored, a goal not touched here is as stored, and the reader's choice decides the rest", () => {
  const loaded = [goal(1, "Retire at 60"), goal(2, "A new car"), goal(3, "Emergency fund")];
  const mineOnly = { ...loaded[0], name: "Retire at 58" };
  const drafts: GoalDraft[] = [
    { kind: "changed", ref: "id:1", goal: loaded[0], now: mineOnly },
    { kind: "kept", ref: "id:2", goal: loaded[1] },
    { kind: "changed", ref: "id:3", goal: loaded[2], now: { ...loaded[2], name: "Six months aside" } },
    { kind: "added", ref: "new:1", now: NEW },
  ];
  // Elsewhere: 2 changed by the chat, 3 deleted, 9 added.
  const stored = [loaded[0], { ...loaded[1], name: "A new bike" }, goal(9, "Added in the chat")];
  const here = resolve(drafts, stored, "here");
  assert.deepEqual(
    here.map((d) => [d.kind, shownAs(d).name]),
    [
      ["changed", "Retire at 58"],
      ["kept", "A new bike"],
      ["kept", "Added in the chat"],
      ["added", "A sabbatical"],
      ["added", "Six months aside"],
    ],
  );
  const theirs = resolve(drafts, stored, "stored");
  assert.deepEqual(
    theirs.map((d) => [d.kind, shownAs(d).name]),
    [
      ["changed", "Retire at 58"],
      ["kept", "A new bike"],
      ["kept", "Added in the chat"],
      ["added", "A sabbatical"],
    ],
  );
});

test("a goal written is as stored, a deleted one gone, a refused one waits with its sentence", () => {
  const g = goal(5, "Retire at 60");
  assert.deepEqual(written({ kind: "added", ref: "new:1", now: NEW }, goal(11, "A sabbatical")), { kind: "kept", ref: "new:1", goal: goal(11, "A sabbatical") });
  assert.equal(written({ kind: "deleted", ref: "id:5", goal: g }, null), null);
  assert.deepEqual(refusedAt({ kind: "added", ref: "new:1", now: NEW }, "currency: not a currency code"), {
    kind: "added", ref: "new:1", now: NEW, error: "currency: not a currency code",
  });
  assert.deepEqual(refusedAt({ kind: "kept", ref: "id:5", goal: g }, "x"), { kind: "kept", ref: "id:5", goal: g });
});

test("a change begun before a save lands on its own goal after it, wherever the save put it", () => {
  // A goal added, then written by a save: it is stored now, and kept in the
  // list's second place after a goal the chat added before it.
  const before = add(fromStored([goal(1, "Retire at 60")]), NEW);
  const editing = before[1].ref;
  const saved = written(before[1], goal(12, "A sabbatical"));
  assert.ok(saved);
  const after = resolve([before[0], saved], [goal(1, "Retire at 60"), goal(9, "Added in the chat"), goal(12, "A sabbatical")], "here");
  assert.deepEqual(after.map((d) => d.ref), ["id:1", "id:9", editing]);
  const changed = changeRef(after, editing, { ...NEW, monthly_contribution: 500 });
  assert.deepEqual(changed.map((d) => [d.kind, d.ref]), [["kept", "id:1"], ["kept", "id:9"], ["changed", editing]]);
  assert.deepEqual(writeOf(changed[2]), { method: "PUT", id: 12, body: { ...NEW, monthly_contribution: 500 } });
  // A goal gone from the page meanwhile: what was typed is added, not dropped.
  assert.deepEqual(changeRef(after, "id:404", NEW).map((d) => d.kind), ["kept", "kept", "kept", "added"]);
});
