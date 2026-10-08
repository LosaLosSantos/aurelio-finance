/* The pages a web search found, as the chat panel lists them.

   Brief AG: each page arrives on the stream when OpenRouter hands it over and
   is stored where the search ran. These pin the two rules the panel keeps:
   pages grow the list they arrived after, the way the server stores them
   (backend/app/chat.py, `_found`), and only a web address becomes a link.

   Run by `npm test` with Node's own test runner. Type-checked by `tsc -b`
   through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { linkOf, withSource } from "../src/components/webSources.ts";

type Block = { kind: "text"; text: string } | { kind: "sources"; pages: { url: string; title: string }[] };

const VOO = { url: "https://investor.example/voo", title: "VOO fact sheet" };
const SEC = { url: "https://www.sec.example/prospectus.htm", title: "Prospectus" };
const NEWS = { url: "https://news.example/etf", title: "ETF news" };

test("a first page starts a list after what was already said", () => {
  const before: Block[] = [{ kind: "text", text: "Cerco." }];
  assert.deepEqual(withSource(before, VOO), [
    { kind: "text", text: "Cerco." },
    { kind: "sources", pages: [VOO] },
  ]);
  assert.deepEqual(before, [{ kind: "text", text: "Cerco." }], "the blocks given are not changed");
});

test("the next page joins the list it arrived after", () => {
  const one = withSource([] as Block[], VOO);
  assert.deepEqual(withSource(one, SEC), [{ kind: "sources", pages: [VOO, SEC] }]);
});

test("a page after words starts a list of its own, where that search ran", () => {
  let blocks: Block[] = withSource([] as Block[], VOO);
  blocks = [...blocks, { kind: "text", text: "Lo 0,03%." }];
  assert.deepEqual(withSource(blocks, NEWS), [
    { kind: "sources", pages: [VOO] },
    { kind: "text", text: "Lo 0,03%." },
    { kind: "sources", pages: [NEWS] },
  ]);
});

test("a page the answer already lists is not listed again", () => {
  let blocks: Block[] = withSource([] as Block[], VOO);
  blocks = [...blocks, { kind: "text", text: "Lo 0,03%." }];
  assert.deepEqual(withSource(blocks, { url: VOO.url, title: "VOO, again" }), [
    { kind: "sources", pages: [VOO] },
    { kind: "text", text: "Lo 0,03%." },
  ]);
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
