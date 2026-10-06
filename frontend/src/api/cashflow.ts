import { api } from "./client";
import type { Schemas } from "./types";

export type IncomeSource = Schemas["IncomeSourceRead"];
export type IncomeSourceCreate = Schemas["IncomeSourceCreate"];
export type Expense = Schemas["ExpenseRead"];
export type ExpenseCreate = Schemas["ExpenseCreate"];
export type CashFlowSummary = Schemas["CashFlowSummary"];

export async function getIncomeSources(): Promise<IncomeSource[]> {
  return (await api.get<IncomeSource[]>("/api/income-sources")).data;
}

export async function createIncomeSource(
  data: IncomeSourceCreate,
): Promise<IncomeSource> {
  return (await api.post<IncomeSource>("/api/income-sources", data)).data;
}

export async function getExpenses(): Promise<Expense[]> {
  return (await api.get<Expense[]>("/api/expenses")).data;
}

export async function createExpense(data: ExpenseCreate): Promise<Expense> {
  return (await api.post<Expense>("/api/expenses", data)).data;
}

export async function getCashFlowSummary(): Promise<CashFlowSummary> {
  return (await api.get<CashFlowSummary>("/api/dashboard/cashflow")).data;
}

// DELETE /api/income-sources/{id}
export async function deleteIncomeSource(id: number): Promise<void> {
  await api.delete(`/api/income-sources/${id}`);
}

// DELETE /api/expenses/{id}
export async function deleteExpense(id: number): Promise<void> {
  await api.delete(`/api/expenses/${id}`);
}

// PUT /api/income-sources/{id}
export async function updateIncomeSource(
  id: number,
  data: IncomeSourceCreate,
): Promise<IncomeSource> {
  return (await api.put<IncomeSource>(`/api/income-sources/${id}`, data)).data;
}

// PUT /api/expenses/{id}
export async function updateExpense(
  id: number,
  data: ExpenseCreate,
): Promise<Expense> {
  return (await api.put<Expense>(`/api/expenses/${id}`, data)).data;
}
