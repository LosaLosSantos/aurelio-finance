/* The pages a web search found, as the chat panel lists them.

   Brief AG: the chat searches the web through OpenRouter, and each page a
   search found arrives on the stream when it is handed over, then is stored
   where the search ran. Two jobs live here: growing an answer's blocks as
   pages arrive, by the same rule the server stores them, so a live answer and
   the same answer read back from the history look alike; and turning a page
   into a link only when it is a web address. The server already refuses
   anything else, and this refuses it again, because a link is something the
   reader presses.

   No runtime imports, so `npm test` reaches it. */

/** One page: where it is and what it is called. */
export interface WebPage {
  url: string;
  title: string;
}

/** The pages one search, or a run of searches, found: the stored block. */
export interface SourcesBlock {
  kind: "sources";
  pages: WebPage[];
}

function isSources(block: { kind: string }): block is SourcesBlock {
  return block.kind === "sources";
}

/** The answer's blocks with `page` added where it arrived: onto the list of
    pages the last block already is, or as a new list after it. A page the
    answer already lists is not listed again. */
export function withSource<B extends { kind: string }>(
  blocks: readonly (B | SourcesBlock)[],
  page: WebPage,
): (B | SourcesBlock)[] {
  if (blocks.some((b) => isSources(b) && b.pages.some((p) => p.url === page.url))) {
    return [...blocks];
  }
  const last = blocks[blocks.length - 1];
  if (last !== undefined && isSources(last)) {
    return [...blocks.slice(0, -1), { kind: "sources", pages: [...last.pages, page] }];
  }
  return [...blocks, { kind: "sources", pages: [page] }];
}

/** A page as a link: its address, the words to show, and the site it is on. */
export interface Link {
  href: string;
  label: string;
  host: string;
}

/** The link for `page`, or null when its address is not http or https: a
    `javascript:` address would run in the page, and nothing else is a web
    page. With no title, the site's name is the label. */
export function linkOf(page: WebPage): Link | null {
  let parsed: URL;
  try {
    parsed = new URL(page.url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  const host = parsed.hostname.replace(/^www\./, "");
  return { href: parsed.href, label: page.title.trim() || host, host };
}
