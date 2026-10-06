/* What the instrument picker says while the fund catalogue is not there yet.

   Brief AB: the "Download it now" button is gone, because the app downloads
   the catalogue by itself. These pin the sentence that took its place: one
   per state of the download, only while the catalogue is empty, in the
   reader's words and never in the fields' names.

   Run by `npm test` with Node's own test runner, which strips the types
   itself. Type-checked by `tsc -b` through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { catalogueNotice, type CatalogueState } from "../src/components/catalogueNotice.ts";

const clock = (iso: string) => iso.slice(11, 16);
const EM_DASH = String.fromCharCode(0x2014);

test("nothing is said once the catalogue has funds, whatever its download is doing", () => {
  const states: CatalogueState["state"][] = ["ready", "downloading", "failed", "not_started"];
  for (const state of states) {
    assert.equal(catalogueNotice({ rows: 4612, state, retry_after: null }, clock), null);
  }
  assert.equal(catalogueNotice(null, clock), null, "not asked yet: nothing to say");
});

test("an empty catalogue says where its download stands", () => {
  const downloading = catalogueNotice({ rows: 0, state: "downloading", retry_after: null }, clock);
  assert.match(downloading ?? "", /^The fund catalogue is downloading by itself\./);

  const failed = catalogueNotice(
    { rows: 0, state: "failed", retry_after: "2026-10-04T12:10:00+00:00" },
    clock,
  );
  assert.match(failed ?? "", /could not be downloaded from justETF/);
  assert.match(failed ?? "", /when it is next opened or reloaded, from 12:10\./);

  const notStarted = catalogueNotice({ rows: 0, state: "not_started", retry_after: null }, clock);
  assert.match(notStarted ?? "", /Reload the page to start it\./);
});

test("every sentence keeps the typed name usable and offers no button", () => {
  const states: CatalogueState["state"][] = ["downloading", "failed", "not_started"];
  for (const state of states) {
    const said = catalogueNotice({ rows: 0, state, retry_after: null }, clock) ?? "";
    assert.match(said, /Meanwhile, what you type can be used as it is\.$/);
    assert.doesNotMatch(said, /Download it now|rows|fetched_at|retry_after/);
    assert.ok(!said.includes(EM_DASH), "no em dash in what the reader sees");
  }
});
