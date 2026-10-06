import { api } from "./client";
import type { Schemas } from "./types";

/* The watchlist: instruments the chat suggested and the reader kept.

   Read and delete, and there is no create here because nothing in the app
   creates one except accepting a suggestion card — which happens through
   `POST /api/chat/cards/{id}`, not through this resource. The day the reader
   wants to add one by hand, the POST arrives with the screen that fills it in.

   Nothing here is owned: a line moves no total, no allocation and no cash
   projection. That is what makes it safe for a model to propose in the first
   place. */
export type WatchlistItem = Schemas["WatchlistItemRead"];

// GET /api/watchlist — most recently added first.
export async function getWatchlist(): Promise<WatchlistItem[]> {
  return (await api.get<WatchlistItem[]>("/api/watchlist")).data;
}

// DELETE /api/watchlist/{id} — drop one idea. Nothing is recomputed, because
// it owned nothing.
export async function deleteWatchlistItem(id: number): Promise<void> {
  await api.delete(`/api/watchlist/${id}`);
}
