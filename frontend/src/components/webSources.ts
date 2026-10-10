/* The pages a web search found, as the chat panel lists them.

   Brief AG gave the chat the web, and since brief AM the app runs each search
   itself: what a search found arrives on the stream whole when it comes back,
   under the search's line, with the query the app sent, and is stored the
   same way, so a live answer and the same answer read back from the history
   look alike. Two jobs live here: the words above a search's list, which say
   what was searched for; and turning a page into a link only when it is a
   web address. The server already refuses anything else, and this refuses it
   again, because a link is something the reader presses.

   No runtime imports, so `npm test` reaches it. */

/** One page: where it is and what it is called. */
export interface WebPage {
  url: string;
  title: string;
}

/** What heads one search's list: the words, and the query the app sent when
    the list says it (every list stored since brief AM does). */
export interface FoundOn {
  words: string;
  query: string | null;
}

/** The heading for a list of `links` pages that a search for `query` found,
    or null when there is nothing to say: a list stored before queries were,
    with no page that can be a link. A search that ran and found nothing still
    says what it looked for, since that query went out all the same. */
export function foundOn(query: string | null | undefined, links: number): FoundOn | null {
  const asked = query?.trim() ?? "";
  if (asked === "") return links > 0 ? { words: "Found on the web", query: null } : null;
  return { words: links > 0 ? "Found on the web for" : "Found nothing on the web for", query: asked };
}

/** A page as a link: its address, the words to show, and the site it is on. */
export interface Link {
  href: string;
  label: string;
  host: string;
}

/* Titles that name no page: what a search hands over for a file whose own
   title says nothing. In the reader's round (2026-10-08) a source was listed
   as "Document". Matched whole, in any case. */
const SAYS_NOTHING = new Set([
  "document",
  "untitled",
  "untitled document",
  "pdf",
  "file",
  "download",
  "home",
  "index",
  "page",
  "null",
]);

/** A name for a page out of its address: the last part of its path, made
    readable ("example-fund-factsheet.pdf" reads "example fund factsheet"),
    or the site when that part holds no word of three letters or more (a
    number, a code, "a"). */
function fromAddress(url: URL, host: string): string {
  let last = url.pathname.split("/").filter(Boolean).pop() ?? "";
  try {
    last = decodeURIComponent(last);
  } catch {
    /* a malformed escape: the part as it is */
  }
  const words = last
    .replace(/\.[a-z0-9]{1,5}$/i, "")
    .replace(/[-_+.]+/g, " ")
    .trim();
  return /\p{L}{3,}/u.test(words) ? words : host;
}

/** The link for `page`, or null when its address is not http or https: a
    `javascript:` address would run in the page, and nothing else is a web
    page. A title that names nothing (none, a word like "Document", the bare
    site) gives way to a name read off the address. */
export function linkOf(page: WebPage): Link | null {
  let parsed: URL;
  try {
    parsed = new URL(page.url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  const host = parsed.hostname.replace(/^www\./, "");
  const title = page.title.trim();
  const bare = title.toLowerCase().replace(/^www\./, "");
  const named = title !== "" && !SAYS_NOTHING.has(bare) && bare !== host;
  return { href: parsed.href, label: named ? title : fromAddress(parsed, host), host };
}
