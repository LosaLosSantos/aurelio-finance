/* Every text at WCAG AA, read off index.css itself (brief AY).

   Each text token reads 4.5:1 or more on every fill the pages paint it on, in
   the light theme and in the dark one; a gain stands as far from the accent
   as the dark theme keeps them; the question in an empty box reads a token of
   its own in both themes. Where each token is painted is the census's and the
   source's (every state in Edge, every fill class read for the text tokens
   inside it), written out below. A failure names the token, its value, the
   fill and the ratio, so whoever moves a colour knows what to move. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

/** What is between the braces of the block that `start` opens. */
function block(start: string): string {
  const at = css.indexOf(start);
  assert.notEqual(at, -1, `index.css has no ${start} block`);
  const open = css.indexOf("{", at);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i);
  }
  throw new Error(`index.css never closes its ${start} block`);
}

/** The colour tokens a block declares, by name without `--color-`. */
function declared(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/--color-([a-z0-9-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

const LIGHT_OWN = declared(block("@theme static"));
const DARK_OWN = declared(block(':root[data-theme="dark"]'));
// The dark block sits on the same root and wins: a token it does not declare
// keeps the light declaration, and a var() reads the dark tokens.
const THEMES = { light: LIGHT_OWN, dark: { ...LIGHT_OWN, ...DARK_OWN } };

/** A token's colour in a theme, as #rrggbb, its var() followed. */
function colour(theme: Record<string, string>, name: string): string {
  let value = theme[name];
  for (let hops = 0; value?.startsWith("var(--color-"); hops++) {
    assert.ok(hops < 4, `--color-${name} goes round in var()`);
    value = theme[value.slice("var(--color-".length, -1)];
  }
  assert.match(value ?? "", /^#([0-9a-f]{3}|[0-9a-f]{6})$/i, `--color-${name} is not a plain colour`);
  const hex = (value ?? "").toLowerCase();
  return hex.length === 4 ? "#" + [...hex.slice(1)].map((c) => c + c).join("") : hex;
}

/** A colour as its three channels, 0 to 255. */
type RGB = number[];

const rgb = (hex: string): RGB => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const hexOf = (c: RGB) => "#" + c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
const linear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

function luminance(c: RGB): number {
  const [r, g, b] = c.map((v) => linear(v / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: RGB, b: RGB): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

/** OKLab distance x 100, the measure brief AX kept the dark theme's colours apart by. */
function distance(a: string, b: string): number {
  const lab = (hex: string) => {
    const [r, g, b2] = rgb(hex).map((c) => linear(c / 255));
    const [l, m, s] = [
      0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b2,
      0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b2,
      0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b2,
    ].map(Math.cbrt);
    return [
      0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
    ];
  };
  const [p, q] = [lab(a), lab(b)];
  return 100 * Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
}

/** `top` at `alpha` over `under`, as the browser lays a translucent fill. */
function over(top: RGB, alpha: number, under: RGB): RGB {
  return top.map((c, i) => c * alpha + under[i] * (1 - alpha));
}

// Each text token and the fills the pages paint it on, the same in both
// themes. "olive/5" is the paid-before notice's band: the olive at 5% over
// the ground (bg-olive/5).
const PAINTED_ON: Record<string, string[]> = {
  ink: ["ground", "surface", "tint", "warn-tint", "up-tint", "down-tint", "olive-tint", "olive/5"],
  "ink-soft": ["ground", "surface", "tint", "warn-tint", "olive-tint", "olive/5"],
  "ink-faint": ["ground", "surface", "tint", "warn-tint", "olive/5"],
  placeholder: ["surface"],
  olive: ["ground", "surface", "tint", "warn-tint", "olive-tint", "olive/5"],
  "olive-deep": ["surface", "tint", "olive-tint"],
  up: ["ground", "surface", "tint", "up-tint"],
  down: ["ground", "surface", "tint", "down-tint"],
  warn: ["ground", "surface", "tint", "warn-tint"],
  "on-accent": ["olive", "olive-deep"],
  "rail-ink": ["rail", "rail-deep"],
};

function fill(theme: Record<string, string>, name: string): RGB {
  return name === "olive/5"
    ? over(rgb(colour(theme, "olive")), 0.05, rgb(colour(theme, "ground")))
    : rgb(colour(theme, name));
}

/** Every pair below 4.5:1 in a theme, one line each; a token the theme does
    not declare is a line too. */
function belowAA(theme: Record<string, string>): string[] {
  const lines: string[] = [];
  for (const [text, fills] of Object.entries(PAINTED_ON)) {
    if (!(text in theme)) {
      lines.push(`no --color-${text} in this theme`);
      continue;
    }
    for (const under of fills) {
      const [fg, bg] = [colour(theme, text), fill(theme, under)];
      const ratio = contrast(rgb(fg), bg);
      if (ratio < 4.5) lines.push(`${text} ${fg} on ${under} ${hexOf(bg)} reads ${ratio.toFixed(2)}, below 4.5`);
    }
  }
  return lines;
}

test("every text token reads 4.5:1 or more on every fill it is painted on, in the light theme", () => {
  assert.deepEqual(belowAA(THEMES.light), []);
});

test("every text token reads 4.5:1 or more on every fill it is painted on, in the dark theme", () => {
  assert.deepEqual(belowAA(THEMES.dark), []);
});

test("a gain stands as far from the accent as the dark theme keeps them, in both themes", () => {
  for (const [name, theme] of Object.entries(THEMES)) {
    const [olive, up] = [colour(theme, "olive"), colour(theme, "up")];
    const apart = distance(olive, up);
    assert.ok(
      apart >= 8.1,
      `${name}: olive ${olive} and up ${up} are ${apart.toFixed(1)} apart in OKLab (x100), below 8.1`,
    );
  }
});

test("the question in an empty box reads a token of its own, in each theme", () => {
  assert.ok("placeholder" in LIGHT_OWN, "the light tokens declare no --color-placeholder");
  assert.ok("placeholder" in DARK_OWN, "the dark block declares no --color-placeholder");
  const rule = css.match(/(^|[}\s])::placeholder\s*\{([^}]*)\}/);
  assert.ok(rule, "index.css has no ::placeholder rule of its own");
  assert.match(rule[2], /color:\s*var\(--color-placeholder\)/, "the ::placeholder rule does not read the token");
});
