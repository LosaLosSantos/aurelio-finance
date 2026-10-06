/* Regenerate src/api/schema.d.ts from the backend's own OpenAPI document.
 *
 * WHY THIS EXISTS. Twenty-three TypeScript interfaces used to be transcribed by
 * hand from the Pydantic models, each with a comment saying "Mirrors XRead on
 * the backend", and nothing checked the transcription. Two of them had drifted,
 * and both drifts hid a feature that had been built: add a field on the
 * backend, forget the second place, and TypeScript stays green while the
 * feature simply never appears. That is the worst failure mode in the codebase
 * because it is silent by construction — there is no error to notice.
 *
 * Wired into `npm run build` (before tsc) so the same drift is now a type
 * error instead of an absence.
 *
 * It does NOT need the backend running: `app.openapi()` builds the document
 * from the routers directly, so a clean checkout builds without :8000 being up.
 * What it does need is the backend venv. When that is missing — someone
 * building the frontend alone — we warn and keep the committed schema.d.ts
 * rather than failing: the file is versioned precisely so that case works.
 * A venv that IS there and fails is a hard error; that one is real.
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, "..");
const BACKEND = resolve(FRONTEND, "..", "backend");
const OUT = join(FRONTEND, "src", "api", "schema.d.ts");
// Inside node_modules on purpose: it is a build intermediate, not a source
// file, and nothing should be tempted to edit or commit it.
const SPEC = join(FRONTEND, "node_modules", ".tmp", "openapi.json");

const BANNER = `/**
 * GENERATED FILE — do not edit by hand.
 *
 * Produced from the backend's OpenAPI document by \`npm run gen:types\`, which
 * \`npm run build\` runs before tsc. To change a type here, change the Pydantic
 * model in backend/app/schemas.py and rebuild: this file is the transcription
 * that used to be done by hand, and drifted.
 */

`;

// The venv interpreter, whichever platform laid it out.
function findPython() {
  for (const rel of [
    join(".venv", "Scripts", "python.exe"),
    join(".venv", "bin", "python"),
  ]) {
    const p = join(BACKEND, rel);
    if (existsSync(p)) return p;
  }
  return null;
}

const python = findPython();
if (!python) {
  const kept = existsSync(OUT) ? "so the committed src/api/schema.d.ts is kept" : "and no committed src/api/schema.d.ts to keep";
  console.warn(`gen:types: no backend venv under ${BACKEND}, ${kept}.`);
  process.exit(existsSync(OUT) ? 0 : 1);
}

mkdirSync(dirname(SPEC), { recursive: true });
const dump = spawnSync(python, [join(BACKEND, "scripts", "dump_openapi.py"), SPEC], {
  cwd: BACKEND,
  encoding: "utf-8",
});
if (dump.status !== 0) {
  console.error(dump.stderr || dump.stdout || `exited ${dump.status}`);
  throw new Error("gen:types: the backend could not describe itself. See the traceback above.");
}

const ast = await openapiTS(pathToFileURL(SPEC), {
  alphabetize: true,
  // OFF, and this is the one setting worth explaining. Left on (the default),
  // a property that merely HAS a default is emitted as required — so
  // `TransactionCreate.fees`, which the backend is perfectly happy to fill in
  // with 0, would become a field every caller must pass. That is the wrong
  // direction: a default makes a field optional on the way IN.
  //
  // On the way OUT it is the opposite — FastAPI serializes the whole response
  // model, so a defaulted field is always present — and THAT is said on the
  // backend instead, by `schemas.API_OUT`, which marks defaulted fields
  // required in the serialization schema only. Optional going in, guaranteed
  // coming out, each stated where it is true.
  defaultNonNullable: false,
});
const next = BANNER + astToString(ast);

// Only write on a real change: an untouched mtime keeps tsc's incremental build
// and vite's dev server from rebuilding the world on every `npm run build`.
const prev = existsSync(OUT) ? readFileSync(OUT, "utf-8") : null;
if (prev === next) {
  console.log("gen:types: src/api/schema.d.ts already matches the backend.");
} else {
  writeFileSync(OUT, next, "utf-8");
  console.log(`gen:types: wrote src/api/schema.d.ts (${next.split("\n").length} lines).`);
}
