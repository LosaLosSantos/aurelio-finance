import { THEME_KEY, appliedTheme, readChoice, type ThemeChoice } from "./components/theme.ts";

/* The page's side of components/theme.ts: what the browser keeps, the
   system's preference, and the `data-theme` the stylesheet reads on the root.

   index.html has set the attribute before the first paint; this module keeps
   it in step afterwards. On System the page follows the system when it
   changes (the evening switch to dark, for one), and a choice made in another
   tab of the app follows here too. */

const DARK = "(prefers-color-scheme: dark)";

let current: ThemeChoice = "system";

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
  });
}
