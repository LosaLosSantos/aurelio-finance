import { api } from "./client";
import type { Schemas } from "./types";

export type Goal = Schemas["GoalRead"];
export type GoalCreate = Schemas["GoalCreate"];
export type RequiredReturnRequest = Schemas["RequiredReturnRequest"];
export type RequiredReturnResult = Schemas["RequiredReturnResult"];

export async function getGoals(): Promise<Goal[]> {
  return (await api.get<Goal[]>("/api/goals")).data;
}

export async function createGoal(data: GoalCreate): Promise<Goal> {
  return (await api.post<Goal>("/api/goals", data)).data;
}

export async function deleteGoal(id: number): Promise<void> {
  await api.delete(`/api/goals/${id}`);
}

export async function updateGoal(id: number, data: GoalCreate): Promise<Goal> {
  return (await api.put<Goal>(`/api/goals/${id}`, data)).data;
}

export async function computeRequiredReturn(
  req: RequiredReturnRequest,
): Promise<RequiredReturnResult> {
  return (await api.post<RequiredReturnResult>("/api/planning/required-return", req))
    .data;
}
