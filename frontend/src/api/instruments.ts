import { api } from "./client";
import type { Schemas } from "./types";

// The local instrument registry. Search is answered from SQLite, so it is
// instant and works with no network. The download is the app's own: every page
// load asks for it (`ensureCatalogue`), and the backend fetches it in the
// background when it is missing or a week old, since the source has no timeout
// of its own.

export type InstrumentMember = Schemas["InstrumentMember"];
export type InstrumentFamily = Schemas["InstrumentFamily"];
export type CatalogueStatus = Schemas["CatalogueStatus"];
export type InstrumentSearch = Schemas["InstrumentSearch"];
export type QuotableInstrument = Schemas["QuotableInstrument"];
export type SymbolLookup = Schemas["SymbolLookup"];

export async function searchInstruments(q: string): Promise<InstrumentSearch> {
  return (await api.get<InstrumentSearch>("/api/instruments/search", { params: { q } })).data;
}

export async function getCatalogueStatus(): Promise<CatalogueStatus> {
  return (await api.get<CatalogueStatus>("/api/instruments/catalogue")).data;
}

// Answered at once: the backend starts a download only when one is due and
// none is running, and never makes the page wait for justETF.
export async function ensureCatalogue(): Promise<CatalogueStatus> {
  return (await api.post<CatalogueStatus>("/api/instruments/catalogue/ensure")).data;
}

// The live lane: shares, ETFs, crypto and futures — everything the fund
// catalogue cannot hold, and the only source of a symbol that actually prices.
export async function lookupSymbols(q: string): Promise<SymbolLookup> {
  return (await api.get<SymbolLookup>("/api/instruments/lookup", { params: { q } })).data;
}
