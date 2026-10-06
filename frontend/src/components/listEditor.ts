import { useState, type FormEvent } from "react";
import { refusal, type Need } from "./required";
import { apiError } from "./ui";

/* The controller behind "a list of things, with a form above it that both adds
   and edits" — the shape this app is built out of, written thirteen times.

   What repeated was never the markup. The forms genuinely differ: a balance
   takes a date and a number, a plan takes a name, a frequency, a source and a
   list of targets. What repeated underneath was always the same four decisions,
   and each of the thirteen copies made them independently:

     - one `editId` that turns the SAME form from "add" into "save", instead of
       a second form somewhere else that drifts from the first;
     - a draft cleared on cancel, on save, and on deleting the row being edited
       — that last one is the case a copy forgets, and it leaves the form
       claiming to edit a row that no longer exists;
     - create-or-update chosen from `editId`, never from which button was
       clicked;
     - every failure through `apiError`, so the backend's own sentence reaches
       the reader instead of "Save failed."

   The draft is a flat map of strings because that is what an <input> holds:
   `toDraft` fills it from a row, `toPayload` turns it back into a request body,
   and those two functions are the only place a call site has to know its own
   field names. */

/** What the form holds while it is being typed: every input's raw string. */
export type Draft = Record<string, string>;

export function useListEditor<T extends { id: number }, P>(opts: {
  /** The empty form — what "add" starts from, and what Cancel returns to. */
  blank: Draft;
  /** How an existing row fills the form for editing. */
  toDraft: (item: T) => Draft;
  /** What this form cannot be sent without (see `required.ts`). A press with
      one of them empty says which, instead of sending nothing in silence. */
  needs: Need[];
  /** The request body for the current draft. Called only once `needs` has
      nothing left to say. */
  toPayload: (draft: Draft) => P;
  create: (data: P) => Promise<unknown>;
  update: (id: number, data: P) => Promise<unknown>;
  destroy?: (id: number) => Promise<unknown>;
  /** What to ask before deleting. Naming the row is the point: "Delete?" and
      "Delete income 'Salary'?" are answered with different care. */
  confirmDelete?: (item: T) => string;
  /** Reload whatever this list came from. */
  onChanged: () => Promise<void> | void;
  /** Said only when the backend says nothing usable — see `apiError`. */
  saveError?: string;
  deleteError?: string;
}) {
  const [draft, setDraft] = useState<Draft>(opts.blank);
  const [editId, setEditId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setEditId(null);
    setDraft(opts.blank);
  }

  /** `set("amount")` is an onChange handler for the "amount" field. */
  function set(name: string): (value: string) => void {
    return (value) => setDraft((d) => ({ ...d, [name]: value }));
  }

  function startEdit(item: T) {
    setEditId(item.id);
    setDraft(opts.toDraft(item));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const refused = refusal(opts.needs, draft);
    if (refused) {
      setError(refused);
      return;
    }
    const payload = opts.toPayload(draft);
    setSubmitting(true);
    setError(null);
    try {
      if (editId != null) await opts.update(editId, payload);
      else await opts.create(payload);
      reset();
      await opts.onChanged();
    } catch (err) {
      setError(apiError(err, opts.saveError ?? "Save failed."));
    } finally {
      setSubmitting(false);
    }
  }

  async function destroy(item: T) {
    if (!opts.destroy) return;
    if (opts.confirmDelete && !window.confirm(opts.confirmDelete(item))) return;
    setError(null);
    try {
      await opts.destroy(item.id);
      // The row being edited just stopped existing; a form still offering to
      // save it would be offering to save nothing.
      if (editId === item.id) reset();
      await opts.onChanged();
    } catch (err) {
      setError(apiError(err, opts.deleteError ?? "Delete failed."));
    }
  }

  return {
    draft,
    set,
    editId,
    editing: editId != null,
    submitting,
    error,
    reset,
    startEdit,
    submit,
    destroy,
  };
}
