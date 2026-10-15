import { THEME_KEY, appliedTheme, readChoice, storedValue, type ThemeChoice } from "./components/theme.ts";

/* The page's side of components/theme.ts: what the browser keeps, the
   system's preference, and the `data-theme` the stylesheet reads on the root.

   index.html has set the attribute before the first paint; this module keeps
   it in step afterwards. On System the page follows the system when it
   changes (the evening switch to dark, for one), and a choice made in another
   tab of the app follows here too. */

const DARK = "(prefers-color-scheme: dark)";

let current: ThemeChoice = "system";

// A switch on screen, told when another tab changes the choice.
const listeners = new Set<(choice: ThemeChoice) => void>();

function systemDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK).matches;
}

function paint(): void {
  document.documentElement.setAttribute("data-theme", appliedTheme(current, systemDark()));
}

/** The choice the browser keeps: System when it keeps none, or refuses to be
    read (a storage some browsers block). */
export function storedChoice(): ThemeChoice {
  try {
    return readChoice(window.localStorage.getItem(THEME_KEY));
  } catch {
    return "system";
  }
}

/** Called once, at start. */
export function followTheme(): void {
  current = storedChoice();
  paint();
  if (typeof window.matchMedia === "function") {
    window.matchMedia(DARK).addEventListener("change", paint);
  }
  // Another tab's choice, or its storage cleared (a null key).
  window.addEventListener("storage", (e) => {
    if (e.key !== null && e.key !== THEME_KEY) return;
    current = readChoice(e.key === null ? null : e.newValue);
    paint();
    for (const heard of listeners) heard(current);
  });
}

/** The choice the page is painted with now. */
export function currentChoice(): ThemeChoice {
  return current;
}

/** Calls `heard` when another tab changes the choice; returns the way to stop. */
export function onChoiceChange(heard: (choice: ThemeChoice) => void): () => void {
  listeners.add(heard);
  return () => {
    listeners.delete(heard);
  };
}

/** The reader's choice: kept in this browser (System keeps nothing) and
    painted at once. A browser that refuses to keep it still paints it, for
    this page. */
export function chooseTheme(choice: ThemeChoice): void {
  current = choice;
  try {
    const value = storedValue(choice);
    if (value === null) window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, value);
  } catch {
    // Refused: painted for this page, not kept.
  }
  paint();
}
