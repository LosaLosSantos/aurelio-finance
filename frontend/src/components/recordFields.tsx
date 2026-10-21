/* Two fields the Records forms share: an account picked from the list, and a
   labelled day. They lived in CashFlow.tsx, beside the PAC's form; since the
   PAC is set in Portfolio (brief BD), both pages' forms take them from here. */

import type { Institution } from "../api/institutions";
import { inputClass } from "./ui";

export function InstitutionSelect({
  value,
  onChange,
  institutions,
  placeholder = "institution…",
  required = false,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  institutions: Institution[];
  placeholder?: string;
  /** Blank is not an answer here, so the placeholder cannot be chosen back
      once something has been picked. Off by default: a transfer's "from" may
      legitimately be external, and an expense may belong to no account. It is
      on for the two fields of a plan, where blank is the two-null condition
      that made a plan's spending add itself to the net worth. On, the box
      is also aria-required. */
  required?: boolean;
  /** What the box is, as its accessible name. */
  label: string;
}) {
  return (
    <select
      className={inputClass}
      value={value}
      aria-label={label}
      aria-required={required || undefined}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="" disabled={required}>{placeholder}</option>
      {institutions.map((i) => (
        <option key={i.id} value={i.id}>{i.name}</option>
      ))}
    </select>
  );
}

// A small labelled date input (date pickers can't show a placeholder).
export function DateField({
  label,
  value,
  onChange,
  mark,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  /** aria-required, when the form needs this date (see required.ts). */
  mark?: { "aria-required"?: true };
}) {
  return (
    <label className="flex items-center gap-1 text-xs text-ink-soft">
      {label}
      <input className={inputClass} type="date" {...mark} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
