import { api } from "./client";
import type { Schemas } from "./types";
import type { Holding } from "./holdings";

export type PriceQuote = Schemas["PriceQuote"];
export type IsinSuggestion = Schemas["IsinSuggestion"];

// GET /api/prices/quote?symbol=VWCE.MI[&on=YYYY-MM-DD]
// With `on`, returns the close on/just before that date — what makes recording
// a purchase from months ago a matter of typing a date and a quantity.
export async function getQuote(symbol: string, on?: string): Promise<PriceQuote> {
  return (
    await api.get<PriceQuote>("/api/prices/quote", {
      params: on ? { symbol, on } : { symbol },
      timeout: 60_000,
    })
  ).data;
}

// GET /api/prices/listing-currencies -> {symbol: currency} the price cache knows
export async function getListingCurrencies(): Promise<Record<string, string>> {
  return (await api.get<Record<string, string>>("/api/prices/listing-currencies")).data;
}

// GET /api/prices/resolve?isin=...
export async function resolveIsin(isin: string): Promise<IsinSuggestion[]> {
  return (await api.get<IsinSuggestion[]>("/api/prices/resolve", { params: { isin } }))
    .data;
}

// POST /api/holdings/{id}/refresh-price — updates unit_price (and value if qty-based)
export async function refreshHoldingPrice(id: number): Promise<Holding> {
  return (await api.post<Holding>(`/api/holdings/${id}/refresh-price`)).data;
}
