import { api } from "./client";
import type { Schemas } from "./types";

// The live cash register: anchors (an actual balance at a date) + the
// projected position the backend computes from them.

export type CashAnchor = Schemas["CashAnchorRead"];
export type CashAnchorCreate = Schemas["CashAnchorCreate"];
export type CashPosition = Schemas["CashPosition"];

// GET /api/cash-anchors -> every institution's anchors, in one request
export async function getAllCashAnchors(): Promise<CashAnchor[]> {
  return (await api.get<CashAnchor[]>("/api/cash-anchors")).data;
}

// GET /api/institutions/{id}/cash-anchors
export async function getCashAnchors(
  institutionId: number,
): Promise<CashAnchor[]> {
  return (
    await api.get<CashAnchor[]>(`/api/institutions/${institutionId}/cash-anchors`)
  ).data;
}

// POST /api/institutions/{id}/cash-anchors
export async function createCashAnchor(
  institutionId: number,
  data: CashAnchorCreate,
): Promise<CashAnchor> {
  return (
    await api.post<CashAnchor>(
      `/api/institutions/${institutionId}/cash-anchors`,
      data,
    )
  ).data;
}

// PUT /api/cash-anchors/{id}
export async function updateCashAnchor(
  id: number,
  data: CashAnchorCreate,
): Promise<CashAnchor> {
  return (await api.put<CashAnchor>(`/api/cash-anchors/${id}`, data)).data;
}

// DELETE /api/cash-anchors/{id}
export async function deleteCashAnchor(id: number): Promise<void> {
  await api.delete(`/api/cash-anchors/${id}`);
}

// GET /api/institutions/{id}/cash  -> projected position (optionally as of a date)
export async function getCashPosition(
  institutionId: number,
  asOf?: string,
): Promise<CashPosition> {
  const params = asOf ? { as_of: asOf } : undefined;
  return (
    await api.get<CashPosition>(`/api/institutions/${institutionId}/cash`, {
      params,
    })
  ).data;
}

// GET /api/cash/positions -> projected position for every institution
export async function getCashPositions(asOf?: string): Promise<CashPosition[]> {
  const params = asOf ? { as_of: asOf } : undefined;
  return (await api.get<CashPosition[]>("/api/cash/positions", { params })).data;
}
