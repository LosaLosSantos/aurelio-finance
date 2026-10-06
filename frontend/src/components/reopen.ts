import axios from "axios";
import { useEffect, useState } from "react";

/* Reopening a page on a record that may be gone.

   The drill-downs of Records — an account and its situation, a real asset, a
   debt — are App's state, so the chat can be told what is on screen, and so
   they are where you left them when you come back. Which is also how they can
   be wrong: what was open may have been deleted, or renamed, from another
   window while you were elsewhere. So on arrival a page reads its record
   again before drawing anything. One that is gone climbs one level, the rule
   the chat follows for the same page (`app/screen.py`); one still there is
   replaced by what the database says now. Records never reopens on a record
   that does not exist. */

// What a re-read came back with: the record as it is now, GONE when the
// backend says it no longer exists, or null when nothing answered — which says
// nothing either way, so what is on screen stays.
export const GONE = "gone";

export async function reread<T>(load: () => Promise<T>): Promise<T | typeof GONE | null> {
  try {
    return await load();
  } catch (err) {
    return axios.isAxiosError(err) && err.response?.status === 404 ? GONE : null;
  }
}

/** For a page with one record open: whether it has been checked yet. Until it
    has, draw nothing below the breadcrumb. `load` and `onRecord` must be
    stable — a module's fetch function, a state setter. */
export function useReopened<T extends { id: number }>(
  record: T | null,
  load: (id: number) => Promise<T>,
  onRecord: (r: T | null) => void,
): boolean {
  // What was open when the page was arrived at. Captured once, so the check
  // runs for the page you came back to and not for every click inside it.
  const [arrived] = useState(record);
  const [checked, setChecked] = useState(arrived === null);

  useEffect(() => {
    if (arrived === null) return;
    let live = true;
    void reread(() => load(arrived.id)).then((fresh) => {
      if (!live) return;
      if (fresh === GONE) onRecord(null);
      else if (fresh) onRecord(fresh);
      setChecked(true);
    });
    return () => {
      live = false;
    };
  }, [arrived, load, onRecord]);

  return checked;
}
