import { api } from "./client";
import type { Schemas } from "./types";

export type Transaction = Schemas["TransactionRead"];
/* `TransactionWrite`, not `TransactionCreate`. The two differ in one field:
   `institution_id` is required on the way in through this door and optional on
   the one the PAC writes through. A ledger row that names no institution on
   either column spends money no account ever loses — the cash register skips
   it, the position it makes is counted in full, and the purchase adds its own
   cost to the net worth. So the type is the contract: an omitted institution
   is a compile error here rather than a 422 at runtime. */
export type TransactionWrite = Schemas["TransactionWrite"];
export type CatchUpSkip = Schemas["CatchUpSkip"];
export type CatchUpResult = Schemas["CatchUpResult"];

export async function getTransactions(): Promise<Transaction[]> {
  return (await api.get<Transaction[]>("/api/transactions")).data;
}

export async function createTransaction(data: TransactionWrite): Promise<Transaction> {
  return (await api.post<Transaction>("/api/transactions", data)).data;
}

export async function updateTransaction(
  id: number,
  data: TransactionWrite,
): Promise<Transaction> {
  return (await api.put<Transaction>(`/api/transactions/${id}`, data)).data;
}

export async function deleteTransaction(id: number): Promise<void> {
  await api.delete(`/api/transactions/${id}`);
}

// POST /api/transactions/catch-up — idempotent ledger catch-up: a Buy for
// every elapsed, still-unexecuted PAC occurrence, and a dividend entry for
// every ex-date of every position that follows its dividends (stated
// distributing, or no policy, when its own history decides). Call it at app
// start.
export async function catchUp(): Promise<CatchUpResult> {
  return (await api.post<CatchUpResult>("/api/transactions/catch-up")).data;
}
