import { api } from "./client";
import type { Schemas } from "./types";

export type RealAsset = Schemas["RealAssetRead"];
export type RealAssetCreate = Schemas["RealAssetCreate"];
export type RealAssetValuation = Schemas["RealAssetValuationRead"];
export type RealAssetValuationCreate = Schemas["RealAssetValuationCreate"];

export async function getRealAssets(): Promise<RealAsset[]> {
  return (await api.get<RealAsset[]>("/api/real-assets")).data;
}

// GET /api/real-assets/{id} -> one asset, or a 404 when it is gone
export async function getRealAsset(id: number): Promise<RealAsset> {
  return (await api.get<RealAsset>(`/api/real-assets/${id}`)).data;
}

export async function createRealAsset(
  data: RealAssetCreate,
): Promise<RealAsset> {
  return (await api.post<RealAsset>("/api/real-assets", data)).data;
}

export async function getValuations(
  realAssetId: number,
): Promise<RealAssetValuation[]> {
  return (
    await api.get<RealAssetValuation[]>(
      `/api/real-assets/${realAssetId}/valuations`,
    )
  ).data;
}

export async function createValuation(
  realAssetId: number,
  data: RealAssetValuationCreate,
): Promise<RealAssetValuation> {
  return (
    await api.post<RealAssetValuation>(
      `/api/real-assets/${realAssetId}/valuations`,
      data,
    )
  ).data;
}

// DELETE /api/real-assets/{id} (cascades to its valuations)
export async function deleteRealAsset(id: number): Promise<void> {
  await api.delete(`/api/real-assets/${id}`);
}

// DELETE /api/real-asset-valuations/{id}
export async function deleteValuation(id: number): Promise<void> {
  await api.delete(`/api/real-asset-valuations/${id}`);
}

// PUT /api/real-assets/{id}
export async function updateRealAsset(
  id: number,
  data: RealAssetCreate,
): Promise<RealAsset> {
  return (await api.put<RealAsset>(`/api/real-assets/${id}`, data)).data;
}

// PUT /api/real-asset-valuations/{id}
export async function updateValuation(
  id: number,
  data: RealAssetValuationCreate,
): Promise<RealAssetValuation> {
  return (
    await api.put<RealAssetValuation>(`/api/real-asset-valuations/${id}`, data)
  ).data;
}
