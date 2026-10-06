import { api } from "./client";
import type { Schemas } from "./types";

export type Holding = Schemas["HoldingRead"];
export type HoldingCreate = Schemas["HoldingCreate"];

export async function getHoldings(snapshotId: number): Promise<Holding[]> {
  return (await api.get<Holding[]>(`/api/snapshots/${snapshotId}/holdings`)).data;
}

export async function createHolding(
  snapshotId: number,
  data: HoldingCreate,
): Promise<Holding> {
  return (await api.post<Holding>(`/api/snapshots/${snapshotId}/holdings`, data))
    .data;
}

// DELETE /api/holdings/{id}
export async function deleteHolding(id: number): Promise<void> {
  await api.delete(`/api/holdings/${id}`);
}

// PUT /api/holdings/{id}
export async function updateHolding(
  id: number,
  data: HoldingCreate,
): Promise<Holding> {
  return (await api.put<Holding>(`/api/holdings/${id}`, data)).data;
}
