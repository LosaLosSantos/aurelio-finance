import { api } from "./client";
import type { Schemas } from "./types";

export type Institution = Schemas["InstitutionRead"];
export type InstitutionCreate = Schemas["InstitutionCreate"];

// GET /api/institutions  -> list
export async function getInstitutions(): Promise<Institution[]> {
  const res = await api.get<Institution[]>("/api/institutions");
  return res.data;
}

// GET /api/institutions/{id} -> one institution, or a 404 when it is gone
export async function getInstitution(id: number): Promise<Institution> {
  return (await api.get<Institution>(`/api/institutions/${id}`)).data;
}

// POST /api/institutions -> create and return the new institution
export async function createInstitution(
  data: InstitutionCreate,
): Promise<Institution> {
  const res = await api.post<Institution>("/api/institutions", data);
  return res.data;
}

// DELETE /api/institutions/{id} (cascades to its snapshots and holdings)
export async function deleteInstitution(id: number): Promise<void> {
  await api.delete(`/api/institutions/${id}`);
}

// PUT /api/institutions/{id}
export async function updateInstitution(
  id: number,
  data: InstitutionCreate,
): Promise<Institution> {
  return (await api.put<Institution>(`/api/institutions/${id}`, data)).data;
}
