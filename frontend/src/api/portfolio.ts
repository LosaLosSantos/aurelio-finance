import { api } from "./client";
import type { Schemas } from "./types";

export type PortfolioRow = Schemas["PortfolioRow"];
export type Portfolio = Schemas["Portfolio"];
export type PaidProposal = Schemas["PaidProposal"];
export type UnreadPurchases = Schemas["UnreadPurchases"];

// GET /api/dashboard/portfolio[?live=true]
export async function getPortfolio(live = false): Promise<Portfolio> {
  return (await api.get<Portfolio>("/api/dashboard/portfolio", { params: { live } }))
    .data;
}

// POST /api/holdings/{id}/paid-recovery: the figures shown, which the server
// checks against its own before it writes them (brief AW).
export async function acceptPaid(p: PaidProposal): Promise<void> {
  await api.post(`/api/holdings/${p.holding_id}/paid-recovery`, { paid: p.paid, units: p.units });
}

// POST /api/holdings/{id}/paid-recovery/decline
export async function declinePaid(p: PaidProposal): Promise<void> {
  await api.post(`/api/holdings/${p.holding_id}/paid-recovery/decline`);
}

// POST /api/paid-recovery: every proposal shown, in one transaction.
export async function acceptAllPaid(ps: PaidProposal[]): Promise<void> {
  await api.post("/api/paid-recovery", {
    rows: ps.map((p) => ({ holding_id: p.holding_id, paid: p.paid, units: p.units })),
  });
}
