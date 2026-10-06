import { api } from "./client";
import type { Schemas } from "./types";

/* Two types, not one. The API takes a bare answer and returns a STORED one,
   which also carries `id` and `created_at`; a single hand-written interface
   was used for both, so the two stored fields were invisible to the frontend
   — present in every response, declared nowhere, and therefore unusable. */
export type SurveyAnswer = Schemas["SurveyAnswer"];
export type SurveyAnswerRead = Schemas["SurveyAnswerRead"];

export async function getSurvey(): Promise<SurveyAnswerRead[]> {
  return (await api.get<SurveyAnswerRead[]>("/api/survey")).data;
}

// Replaces the whole set of answers with the provided ones.
export async function saveSurvey(
  answers: SurveyAnswer[],
): Promise<SurveyAnswerRead[]> {
  return (await api.put<SurveyAnswerRead[]>("/api/survey", answers)).data;
}
