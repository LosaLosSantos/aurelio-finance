import { api } from "./client";
import type { Schemas } from "./types";

export type PlanTarget = Schemas["PlanTargetRead"];
export type AccumulationPlan = Schemas["AccumulationPlanRead"];
/* `AccumulationPlanWrite`, not `AccumulationPlanCreate`. The two differ in two
   fields: the plan's `source_institution_id` and each target's
   `institution_id` are required on the way in through this door and optional
   on the one `pac.py` writes through. A plan that names neither end spends
   money no account ever loses — the buys it creates carry a null on both
   institution columns, the cash register skips them, and the positions count
   in full. So the type is the contract: an omitted institution is a compile
   error here rather than a 422 at runtime. */
export type AccumulationPlanWrite = Schemas["AccumulationPlanWrite"];

export async function getAccumulationPlans(): Promise<AccumulationPlan[]> {
  return (await api.get<AccumulationPlan[]>("/api/accumulation-plans")).data;
}

export async function createAccumulationPlan(
  data: AccumulationPlanWrite,
): Promise<AccumulationPlan> {
  return (await api.post<AccumulationPlan>("/api/accumulation-plans", data)).data;
}

export async function updateAccumulationPlan(
  id: number,
  data: AccumulationPlanWrite,
): Promise<AccumulationPlan> {
  return (await api.put<AccumulationPlan>(`/api/accumulation-plans/${id}`, data)).data;
}

export async function deleteAccumulationPlan(id: number): Promise<void> {
  await api.delete(`/api/accumulation-plans/${id}`);
}
