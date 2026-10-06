import { api } from "./client";
import type { Schemas } from "./types";

export type OmittedPosition = Schemas["OmittedPosition"];
export type ArrivedPosition = Schemas["ArrivedPosition"];
export type UnconvertedAmount = Schemas["UnconvertedAmount"];
export type DashboardSummary = Schemas["DashboardSummary"];
export type AssetClassSlice = Schemas["AssetClassSlice"];
export type RealCategorySlice = Schemas["RealCategorySlice"];
export type DashboardAllocation = Schemas["DashboardAllocation"];
export type NetWorthPoint = Schemas["NetWorthPoint"];

export async function getSummary(): Promise<DashboardSummary> {
  return (await api.get<DashboardSummary>("/api/dashboard/summary")).data;
}

export async function getAllocation(): Promise<DashboardAllocation> {
  return (await api.get<DashboardAllocation>("/api/dashboard/allocation")).data;
}

export async function getNetWorthSeries(): Promise<NetWorthPoint[]> {
  return (await api.get<NetWorthPoint[]>("/api/dashboard/net-worth-series")).data;
}
