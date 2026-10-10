/* What a web search found, as the chat panel heads and lists it.

   Since brief AM the app runs each search itself, and what a search found
   arrives whole, with the query the app sent, as a list of its own under the
   search's line. These pin the two rules the panel keeps: the heading says
   what was searched for, and whether anything was found; and only a web
   address becomes a link.

   Run by `npm test` with Node's own test runner. Type-checked by `tsc -b`
   through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { foundOn, linkOf } from "../src/components/webSources.ts";

const SEC = { url: "https://www.sec.example/prospectus.htm", title: "Prospectus" };

test("a list says what was searched for, above the pages it found", () => {
  assert.deepEqual(foundOn("S&P 500 UCITS ETF lowest ongoing charge", 5), {
    words: "Found on the web for",
    query: "S&P 500 UCITS ETF lowest ongoing charge",
  });
});

test("a search that found nothing still says what it looked for", () => {
  assert.deepEqual(foundOn("ECB rate decision September 2026", 0), {
    words: "Found nothing on the web for",
    query: "ECB rate decision September 2026",
  });
});

test("a list stored before queries were is headed as it was", () => {
  assert.deepEqual(foundOn(undefined, 2), { words: "Found on the web", query: null });
  assert.deepEqual(foundOn(null, 2), { words: "Found on the web", query: null });
  assert.deepEqual(foundOn("   ", 2), { words: "Found on the web", query: null });
  assert.equal(foundOn(null, 0), null, "and with no link to show, it shows nothing");
});

test("a query is shown without the spaces around it", () => {
  assert.equal(foundOn("  ETF costs  ", 1)?.query, "ETF costs");
});

test("a web page becomes a link, named by its title, on its site", () => {
  assert.deepEqual(linkOf(SEC), {
    href: "https://www.sec.example/prospectus.htm",
    label: "Prospectus",
    host: "sec.example",
  });
  assert.deepEqual(linkOf({ url: "http://plain.example/a", title: "  " }), {
    href: "http://plain.example/a",
    label: "plain.example",
    host: "plain.example",
  });
});

test("nothing that is not a web address becomes a link", () => {
  for (const url of [
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "data:text/html,<p>x</p>",
    "ftp://files.example/report.pdf",
    "file:///C:/Users/x",
    "not a url",
    "",
  ]) {
    assert.equal(linkOf({ url, title: "x" }), null, url);
  }
});

test("a title that names nothing gives way to a name read off the address", () => {
  // Brief AJ: in the reader's round a source was listed as "Document".
  assert.equal(
    linkOf({ url: "https://www.issuer.example/docs/example-fund-factsheet.pdf", title: "Document" })?.label,
    "example fund factsheet",
  );
  assert.equal(linkOf({ url: "https://issuer.example/kid_EXAMPLE%20FUND.pdf", title: "PDF" })?.label, "kid EXAMPLE FUND");
  assert.equal(linkOf({ url: "https://www.news.example/a/b/etf-costs", title: "www.news.example" })?.label, "etf costs");
  assert.equal(linkOf({ url: "https://news.example/2026/10/08", title: "untitled" })?.label, "news.example");
  assert.equal(linkOf({ url: "https://bad.example/%E0%A4%A", title: "" })?.label, "bad.example");
});

test("a title that names its page is kept, whatever the address says", () => {
  assert.equal(
    linkOf({ url: "https://issuer.example/document.pdf", title: "Example Fund: key information" })?.label,
    "Example Fund: key information",
  );
});
