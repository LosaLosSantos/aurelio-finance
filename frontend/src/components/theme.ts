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
