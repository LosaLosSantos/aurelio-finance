/* Which theme a page is painted in (brief AX).

   The rule is components/theme.ts's: the reader's choice kept in this
   browser, or the system's preference. index.html runs the same rule in its
   own few lines of plain script before the first paint, and nothing but this
   test keeps the two equal: the script here is index.html's own, run in a
   sandbox with a stand-in for the browser. Every expected value is written
   out. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import { THEME_KEY, appliedTheme, readChoice } from "../src/components/theme.ts";

// What the browser keeps (null: nothing; "refused": a storage that throws on
// a read, as a blocked one does) -> the theme on a light system, on a dark one.
const TABLE: [string | null, "light" | "dark", "light" | "dark"][] = [
  [null, "light", "dark"],
  ["light", "light", "light"],
  ["dark", "dark", "dark"],
  ["system", "light", "dark"],
  ["", "light", "dark"],
  ["Dark", "light", "dark"],
  ["blue", "light", "dark"],
  ["refused", "light", "dark"],
];

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];

/** index.html's script, run as the browser runs it, against a browser that
    keeps `stored` and whose system does or does not ask for dark. */
function painted(stored: string | null, systemDark: boolean): string | undefined {
  const root: Record<string, string> = {};
  const window = {
    localStorage: {
      getItem(key: string) {
        if (stored === "refused") throw new Error("SecurityError: storage is blocked");
        return key === THEME_KEY ? stored : null;
      },
    },
    matchMedia: (query: string) => ({ matches: query === "(prefers-color-scheme: dark)" && systemDark }),
  };
  const document = {
    documentElement: {
      setAttribute(name: string, value: string) {
        root[name] = value;
      },
    },
  };
  vm.runInNewContext(inline[0][1], { window, document });
  return root["data-theme"];
}

test("a stored value reads as the choice, anything else as System", () => {
  assert.equal(readChoice("light"), "light");
  assert.equal(readChoice("dark"), "dark");
  assert.equal(readChoice(null), "system");
  assert.equal(readChoice(undefined), "system");
  assert.equal(readChoice("system"), "system");
  assert.equal(readChoice("Dark"), "system");
  assert.equal(readChoice(""), "system");
});

test("the stored choice wins over the system; with none, the system decides", () => {
  for (const [stored, onLight, onDark] of TABLE) {
    const choice = readChoice(stored === "refused" ? null : stored);
    assert.equal(appliedTheme(choice, false), onLight, `stored ${stored}, a light system`);
    assert.equal(appliedTheme(choice, true), onDark, `stored ${stored}, a dark system`);
  }
});

test("index.html sets the theme in its head, with one script of its own", () => {
  assert.equal(inline.length, 1, "one inline script");
  assert.ok(inline[0].index! < html.indexOf("</head>"), "in the head, before the body is painted");
  assert.ok(!/\bimport\b/.test(inline[0][1]), "no import: it runs before the app's own code");
});

test("index.html's own script paints what the rule says, a refused storage included", () => {
  for (const [stored, onLight, onDark] of TABLE) {
    assert.equal(painted(stored, false), onLight, `stored ${stored}, a light system`);
    assert.equal(painted(stored, true), onDark, `stored ${stored}, a dark system`);
  }
});
