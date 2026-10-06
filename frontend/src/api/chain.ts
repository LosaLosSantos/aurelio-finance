import { api } from "./client";
import type { Schemas } from "./types";

export type ChainStep = Schemas["ChainStepRead"];
export type ChainRun = Schemas["ChainRunRead"];
export type ChainRunSummary = Schemas["ChainRunSummary"];

// GET /api/advisor/chain/{id} — one analysis run with all its steps.
//
// There is no `runChain` here any more, and its absence is the step: running
// the analyzer is a card the chat proposes and the reader confirms, so the
// only thing left over the wire is the reading. By id and not "the latest",
// because the card that opens this one was written by the run it names.
export async function getChainRun(id: number): Promise<ChainRun> {
  return (await api.get<ChainRun>(`/api/advisor/chain/${id}`)).data;
}

// GET /api/advisor/chain — every run, newest first, and not one word of any of
// them. The app could already address any run by id and had no way to say
// which runs there ARE, so a run whose card had scrolled out of a conversation
// was stored and unreachable at the same time.
//
// Each row carries the confidant's own verdict for that run, which is what
// turns "is this chain adversarial, or is it theatre?" into a count.
export async function listChainRuns(): Promise<ChainRunSummary[]> {
  return (await api.get<ChainRunSummary[]>("/api/advisor/chain")).data;
}
