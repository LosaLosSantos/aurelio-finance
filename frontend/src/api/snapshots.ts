import { api } from "./client";
import type { Schemas } from "./types";

// A snapshot is a dated "situation" of an institution.
// Its `value` is the sum of its holdings (computed by the backend).
// `PrefilledSnapshot` is one started from the previous one, and its
// `needs_attention` names the rows nothing could re-price — the only ones
// actually asking for you.
export type Snapshot = Schemas["SnapshotRead"];
export type SnapshotCreate = Schemas["SnapshotCreate"];
export type PrefilledSnapshot = Schemas["PrefilledSnapshotRead"];

export async function getSnapshots(institutionId: number): Promise<Snapshot[]> {
  return (
    await api.get<Snapshot[]>(`/api/institutions/${institutionId}/snapshots`)
  ).data;
}

export async function createSnapshot(
  institutionId: number,
  data: SnapshotCreate,
): Promise<Snapshot> {
  return (
    await api.post<Snapshot>(`/api/institutions/${institutionId}/snapshots`, data)
  ).data;
}

// A new situation started from the previous one, plus what the app did to it.
// `needs_attention` names the rows nothing could re-price — the only ones
// actually asking for you.
export async function createPrefilledSnapshot(
  institutionId: number,
  data: SnapshotCreate,
): Promise<PrefilledSnapshot> {
  return (
    await api.post<PrefilledSnapshot>(
      `/api/institutions/${institutionId}/snapshots/prefilled`,
      data,
    )
  ).data;
}

// GET /api/snapshots/{id} -> one situation, or a 404 when it is gone
export async function getSnapshot(id: number): Promise<Snapshot> {
  return (await api.get<Snapshot>(`/api/snapshots/${id}`)).data;
}

export async function deleteSnapshot(id: number): Promise<void> {
  await api.delete(`/api/snapshots/${id}`);
}
