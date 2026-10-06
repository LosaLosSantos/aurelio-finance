# Aurelio's frontend

React and TypeScript, built with Vite and styled with Tailwind CSS v4. The
[main README](../README.md) says how to run the whole app; this folder is the
part that runs in the browser.

- `npm run dev`: the development server on <http://localhost:5173>, which sends
  `/api` to the backend on port 8000.
- `npm run build`: regenerates `src/api/schema.d.ts` from the backend's OpenAPI
  document, type-checks, and builds into `dist/`, which the backend serves.
- `npm test`: the unit tests in `tests/`, run by Node's own test runner.
