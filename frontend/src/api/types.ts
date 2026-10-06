import type { components } from "./schema";

/* The backend's own schemas, by name.

   `schema.d.ts` beside this file is GENERATED from the OpenAPI document the
   backend publishes — `npm run gen:types`, which `npm run build` runs before
   tsc. Do not edit it.

   Every response and payload type in api/*.ts used to be transcribed here by
   hand, under a comment promising it "mirrors XRead on the backend", and
   nothing checked the promise. Two had drifted, and each drift hid a feature
   that had been built and paid for: the failure mode is silent by
   construction, because a field the frontend never declares is a field nothing
   asks about. Adding one on the backend and forgetting the second place now
   produces a type error instead of a feature that simply never appears.

   The api/*.ts FUNCTIONS stay hand-written — they are thin, and their comments
   say what each endpoint is for, which no generator knows. Only the shapes
   come from here. Field-level reasoning lives on the Pydantic models in
   backend/app/schemas.py and rides along in the generated JSDoc. */
export type Schemas = components["schemas"];
