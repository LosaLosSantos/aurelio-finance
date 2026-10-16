import { useEffect, useState } from "react";
import { chooseTheme, currentChoice, onChoiceChange } from "../themeRoot.ts";
import { THEME_CHOICES, type ThemeChoice } from "./theme.ts";
import { choiceClass } from "./choice";
import { cardClass } from "./ui";

const LABEL: Record<ThemeChoice, string> = { system: "System", light: "Light", dark: "Dark" };

/* How Aurelio looks in this browser: System, Light or Dark.

   Not a profile answer, and drawn apart from them on purpose. A profile
   answer is saved with "Save profile" and goes to the database; this applies
   on the press, is kept by the browser alone (themeRoot.ts) and is never
   sent anywhere, so it sits in a card of its own, below the profile's save.

   The three are toggle buttons in a group named "Theme", the pattern of the
   Dashboard's chart and table switch: each named by its word, the one in use
   pressed. */
export default function ThemeSection() {
  const [choice, setChoice] = useState<ThemeChoice>(currentChoice);

  // A choice made in another tab of the app shows here too.
  useEffect(() => onChoiceChange(setChoice), []);

  function pick(next: ThemeChoice) {
    chooseTheme(next);
    setChoice(next);
  }

  return (
    <section className={cardClass + " space-y-3 p-5"}>
      <h3 className="text-sm font-semibold text-ink">Theme</h3>
      <p className="text-sm text-ink-soft">
        How Aurelio looks in this browser. System follows your computer's light or dark
        setting.
      </p>
      <div role="group" aria-label="Theme" className="flex flex-wrap gap-2">
        {THEME_CHOICES.map((c) => (
          <button
            key={c}
            type="button"
            aria-pressed={choice === c}
            onClick={() => pick(c)}
            className={choiceClass(choice === c)}
          >
            {LABEL[c]}
          </button>
        ))}
      </div>
      <p className="text-xs text-ink-faint">
        Applies at once, and is kept in this browser only: it is not part of your profile,
        and “Save profile” does not keep it.
      </p>
    </section>
  );
}
