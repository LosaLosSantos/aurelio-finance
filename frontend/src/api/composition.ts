import { api } from "./client";
import type { Schemas } from "./types";

export type AllocationSlice = Schemas["AllocationSlice"];
export type OverlapItem = Schemas["OverlapItem"];
export type MatrixCell = Schemas["MatrixCell"];
export type CompositionRow = Schemas["CompositionRow"];
export type PortfolioComposition = Schemas["PortfolioComposition"];

// GET /api/dashboard/portfolio/composition[?refresh=true]
// Cached per symbol for 15 days; refresh=true refetches from the sources.
export async function getPortfolioComposition(
  refresh = false,
): Promise<PortfolioComposition> {
  return (
    await api.get<PortfolioComposition>("/api/dashboard/portfolio/composition", {
      params: { refresh },
      timeout: 120_000, // first fetch walks external sources per symbol
    })
  ).data;
}
