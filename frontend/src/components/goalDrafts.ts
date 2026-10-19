/* The goals on the Profile tab, held until "Save profile" (brief BC).

   A goal used to be written by its own button the moment it was added,
   changed or deleted, while the answers above it waited for the page's save:
   two saves on one tab, and a reader who pressed the goal's left the answers
   unsaved, nothing said. Now a goal added, changed or deleted waits with the
   answers, said on its row ("not saved") or under the list ("Deleted when
   you save", with a way back, as the other answers do), and the one save
   sends the requests the goal's own buttons sent, with the same bodies, one
   per goal in the list's order.

   The chat writes goals too (`write_goal`), so before writing the save reads
   the goals as stored now and lays the page's over them (`resolve`): a goal
   the reader did not touch is never sent, and one changed on both sides is
   asked about before anything is written, never picked in silence.

   No runtime imports, so `npm test` reaches it. */

import type { Goal, GoalCreate } from "../api/goals";

/** One goal on the page. `ref` names it for as long as the page is open,
    across saves: the form's ✎ holds a ref, never a place in the list, which
    a save can reorder, so a change begun before a save still lands on its
    own goal after it. `error` is the backend's sentence when the last save
    was refused at this goal; it goes with the reader's next change to it. */
export type GoalDraft =
  /** As stored. */
  | { kind: "kept"; ref: string; goal: Goal }
  /** Stored, changed here: `now` is what the save writes over it. */
  | { kind: "changed"; ref: string; goal: Goal; now: GoalCreate; error?: string }
  /** Stored, deleted here: listed under the rest until the save. */
  | { kind: "deleted"; ref: string; goal: Goal; error?: string }
  /** New here: written by the save. */
  | { kind: "added"; ref: string; now: GoalCreate; error?: string };

/** The goal form's boxes, as typed. */
export interface GoalForm {
  name: string;
  type: string;
  currency: string;
  targetAmount: string;
  targetDate: string;
  currentAmount: string;
  monthly: string;
}

/** The body a goal is written with, from its form: the body `Goals.submit`
    sent before brief BC. The name, when left empty, is the type's label
    (`label`); a target's four figures go only with a target_amount goal. */
export function goalBody(f: GoalForm, label: string | null): GoalCreate {
  const isTarget = f.type === "target_amount";
  return {
    name: f.name.trim() || (label ?? f.type),
    type: f.type,
    currency: f.currency.trim(),
    target_amount: isTarget && f.targetAmount ? Number(f.targetAmount) : null,
    target_date: isTarget && f.targetDate ? f.targetDate : null,
    current_amount: isTarget && f.currentAmount ? Number(f.currentAmount) : null,
    monthly_contribution: isTarget && f.monthly ? Number(f.monthly) : null,
  };
}

export function fromStored(goals: Goal[]): GoalDraft[] {
  return goals.map((goal) => ({ kind: "kept", ref: `id:${goal.id}`, goal }));
}

/** The values a row shows: what the save will write, or what is stored. */
export function shownAs(d: GoalDraft): GoalCreate {
  return d.kind === "added" || d.kind === "changed" ? d.now : d.goal;
}

/** A ref no goal on the page has: "new:" and a number. */
function newRef(drafts: GoalDraft[]): string {
  const taken = drafts.map((d) => Number(/^new:(\d+)$/.exec(d.ref)?.[1] ?? 0));
  return `new:${Math.max(0, ...taken) + 1}`;
}

/** A new goal, after the others. */
export function add(drafts: GoalDraft[], now: GoalCreate): GoalDraft[] {
  return [...drafts, { kind: "added", ref: newRef(drafts), now }];
}

/** `at` changed to `now`: a new one stays new, a stored one is changed. */
export function change(drafts: GoalDraft[], at: number, now: GoalCreate): GoalDraft[] {
  return drafts.map((d, i): GoalDraft => {
    if (i !== at || d.kind === "deleted") return d;
    if (d.kind === "added") return { kind: "added", ref: d.ref, now };
    return { kind: "changed", ref: d.ref, goal: d.goal, now };
  });
}

/** The goal `ref` changed to `now`, wherever the list now holds it. A goal no
    longer on the page (deleted elsewhere, and let go) is added as a new one:
    what the reader typed and pressed is never dropped. */
export function changeRef(drafts: GoalDraft[], ref: string, now: GoalCreate): GoalDraft[] {
  const at = drafts.findIndex((d) => d.ref === ref);
  return at < 0 ? add(drafts, now) : change(drafts, at, now);
}

/** `at` deleted: a new one simply goes, a stored one waits for the save. */
export function remove(drafts: GoalDraft[], at: number): GoalDraft[] {
  const d = drafts[at];
  if (!d) return drafts;
  if (d.kind === "added") return drafts.filter((_, i) => i !== at);
  return drafts.map((x, i): GoalDraft => (i === at && x.kind !== "added" ? { kind: "deleted", ref: x.ref, goal: x.goal } : x));
}

/** A deleted one kept after all, as it is stored. */
export function keep(drafts: GoalDraft[], at: number): GoalDraft[] {
  return drafts.map((d, i): GoalDraft => (i === at && d.kind === "deleted" ? { kind: "kept", ref: d.ref, goal: d.goal } : d));
}

/** How many goals a save would write. */
export function pending(drafts: GoalDraft[]): number {
  return drafts.filter((d) => d.kind !== "kept").length;
}

/** The goals the reader has, the deleted ones aside. */
export function counted(drafts: GoalDraft[]): number {
  return drafts.filter((d) => d.kind !== "deleted").length;
}

export type GoalWrite =
  | { method: "POST"; body: GoalCreate }
  | { method: "PUT"; id: number; body: GoalCreate }
  | { method: "DELETE"; id: number };

/** The request a draft sends, or null for one as stored: what the goal's own
    buttons sent before (POST /api/goals, PUT and DELETE /api/goals/{id}). */
export function writeOf(d: GoalDraft): GoalWrite | null {
  if (d.kind === "added") return { method: "POST", body: d.now };
  if (d.kind === "changed") return { method: "PUT", id: d.goal.id, body: d.now };
  if (d.kind === "deleted") return { method: "DELETE", id: d.goal.id };
  return null;
}

/** The same goal, field by field: what "changed elsewhere" is read by. */
export function sameGoal(a: Goal, b: Goal): boolean {
  return (
    a.name === b.name &&
    (a.type ?? null) === (b.type ?? null) &&
    a.currency === b.currency &&
    (a.target_amount ?? null) === (b.target_amount ?? null) &&
    (a.target_date ?? null) === (b.target_date ?? null) &&
    (a.current_amount ?? null) === (b.current_amount ?? null) &&
    (a.monthly_contribution ?? null) === (b.monthly_contribution ?? null) &&
    (a.notes ?? null) === (b.notes ?? null)
  );
}

/** A goal changed or deleted here that was also changed or deleted elsewhere
    since the page read it. */
export interface GoalConflict {
  /** The goal's name as the page read it. */
  name: string;
  /** What happened to it elsewhere. */
  elsewhere: "changed" | "deleted";
  /** What the page holds for it. */
  here: "changed" | "deleted";
}

export function goalConflicts(drafts: GoalDraft[], stored: Goal[]): GoalConflict[] {
  const byId = new Map(stored.map((g) => [g.id, g]));
  const out: GoalConflict[] = [];
  for (const d of drafts) {
    if (d.kind !== "changed" && d.kind !== "deleted") continue;
    const s = byId.get(d.goal.id);
    // Deleted on both sides: the same end, nothing to ask.
    if (!s && d.kind === "deleted") continue;
    if (!s) out.push({ name: d.goal.name, elsewhere: "deleted", here: d.kind });
    else if (!sameGoal(s, d.goal)) out.push({ name: d.goal.name, elsewhere: "changed", here: d.kind });
  }
  return out;
}

/** The page's goals laid over the goals as stored now, in the stored order
    and then the page's new ones. A goal the reader did not touch is taken as
    stored (changed, added or deleted elsewhere). One the reader changed or
    deleted keeps the reader's change, now against the stored version, unless
    it was changed or deleted elsewhere too: then `choice` decides, "here"
    (the reader's: a change of a goal gone elsewhere is written as a new one)
    or "stored" (what is on record: the reader's change of it is dropped). */
export function resolve(drafts: GoalDraft[], stored: Goal[], choice: "here" | "stored"): GoalDraft[] {
  const mine = new Map<number, Extract<GoalDraft, { kind: "changed" | "deleted" }>>();
  for (const d of drafts) if (d.kind === "changed" || d.kind === "deleted") mine.set(d.goal.id, d);
  // A stored goal keeps the ref the page knows it by, a goal written by an
  // earlier save included ("new:" then, not "id:").
  const refs = new Map<number, string>();
  for (const d of drafts) if (d.kind !== "added") refs.set(d.goal.id, d.ref);
  const out: GoalDraft[] = [];
  for (const s of stored) {
    const d = mine.get(s.id);
    mine.delete(s.id);
    const ref = refs.get(s.id) ?? `id:${s.id}`;
    if (!d) out.push({ kind: "kept", ref, goal: s });
    else if (!sameGoal(s, d.goal) && choice === "stored") out.push({ kind: "kept", ref, goal: s });
    else out.push({ ...d, goal: s });
  }
  const added = drafts.filter((d) => d.kind === "added");
  // What is left was deleted elsewhere: a deletion here is done already; a
  // change here is the reader's to keep, as a new goal, or to let go.
  if (choice === "here") {
    for (const d of mine.values()) {
      if (d.kind === "changed") added.push({ kind: "added", ref: d.ref, now: d.now, error: d.error });
    }
  }
  return [...out, ...added];
}

/** A draft after its request was taken: as stored, from the backend's
    answer (POST and PUT answer with the goal), or gone for a deletion. */
export function written(d: GoalDraft, answer: Goal | null): GoalDraft | null {
  if (d.kind === "deleted" || answer === null) return null;
  return { kind: "kept", ref: d.ref, goal: answer };
}

/** A draft whose request was refused: it keeps waiting, with the backend's
    sentence. One as stored sends nothing and cannot be refused. */
export function refusedAt(d: GoalDraft, sentence: string): GoalDraft {
  return d.kind === "kept" ? d : { ...d, error: sentence };
}
