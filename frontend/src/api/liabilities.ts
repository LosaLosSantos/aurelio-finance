import { api } from "./client";
import type { Schemas } from "./types";

// A liability tracks its outstanding principal as dated balances;
// `latest_balance` is the most recent one (computed server-side).

export type Liability = Schemas["LiabilityRead"];
export type LiabilityCreate = Schemas["LiabilityCreate"];
export type LiabilityBalance = Schemas["LiabilityBalanceRead"];
export type LiabilityBalanceCreate = Schemas["LiabilityBalanceCreate"];

export async function getLiabilities(): Promise<Liability[]> {
  return (await api.get<Liability[]>("/api/liabilities")).data;
}

// GET /api/liabilities/{id} -> one debt, or a 404 when it is gone
export async function getLiability(id: number): Promise<Liability> {
  return (await api.get<Liability>(`/api/liabilities/${id}`)).data;
}

export async function createLiability(
  data: LiabilityCreate,
): Promise<Liability> {
  return (await api.post<Liability>("/api/liabilities", data)).data;
}

// PUT /api/liabilities/{id}
export async function updateLiability(
  id: number,
  data: LiabilityCreate,
): Promise<Liability> {
  return (await api.put<Liability>(`/api/liabilities/${id}`, data)).data;
}

// DELETE /api/liabilities/{id} (cascades to its balances)
export async function deleteLiability(id: number): Promise<void> {
  await api.delete(`/api/liabilities/${id}`);
}

export async function getBalances(
  liabilityId: number,
): Promise<LiabilityBalance[]> {
  return (
    await api.get<LiabilityBalance[]>(`/api/liabilities/${liabilityId}/balances`)
  ).data;
}

export async function createBalance(
  liabilityId: number,
  data: LiabilityBalanceCreate,
): Promise<LiabilityBalance> {
  return (
    await api.post<LiabilityBalance>(
      `/api/liabilities/${liabilityId}/balances`,
      data,
    )
  ).data;
}

// PUT /api/liability-balances/{id}
export async function updateBalance(
  id: number,
  data: LiabilityBalanceCreate,
): Promise<LiabilityBalance> {
  return (
    await api.put<LiabilityBalance>(`/api/liability-balances/${id}`, data)
  ).data;
}

// DELETE /api/liability-balances/{id}
export async function deleteBalance(id: number): Promise<void> {
  await api.delete(`/api/liability-balances/${id}`);
}
