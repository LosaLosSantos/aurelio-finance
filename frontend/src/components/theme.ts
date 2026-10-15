/* Which theme a page is painted in: the reader's choice, kept in this
   browser, or the system's preference.

   The rule runs in two places. index.html carries it as a few lines of plain
   script that set `data-theme` on the root before the stylesheet paints the
   first frame, so no page shows the other theme while it loads; themeRoot.ts
   runs it again whenever the system's preference or the choice changes.
   tests/theme.test.ts holds index.html's own script to this module.

   The choice lives in the browser's storage and nowhere else: it is how this
   browser shows the app, not a fact about the reader's money. */

export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

/** The browser storage key that keeps the choice. */
export const THEME_KEY = "aurelio-theme";

/** The three choices, in the order the Profile offers them. */
export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"];

/** What the browser keeps for a choice: System keeps nothing, so a reader who
    never chose and one who chose System read back the same. */
export function storedValue(choice: ThemeChoice): string | null {
  return choice === "system" ? null : choice;
}

/** A stored value read back. Anything but "light" or "dark", nothing stored
    included, is System. */
export function readChoice(stored: string | null | undefined): ThemeChoice {
  return stored === "light" || stored === "dark" ? stored : "system";
}

/** The theme a choice paints, given whether the system asks for dark. */
export function appliedTheme(choice: ThemeChoice, systemDark: boolean): Theme {
  if (choice === "system") return systemDark ? "dark" : "light";
  return choice;
}
