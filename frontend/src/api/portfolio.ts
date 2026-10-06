import { api } from "./client";
import type { Schemas } from "./types";

export type PortfolioRow = Schemas["PortfolioRow"];
export type Portfolio = Schemas["Portfolio"];

// GET /api/dashboard/portfolio[?live=true]
export async function getPortfolio(live = false): Promise<Portfolio> {
  return (await api.get<Portfolio>("/api/dashboard/portfolio", { params: { live } }))
    .data;
}
