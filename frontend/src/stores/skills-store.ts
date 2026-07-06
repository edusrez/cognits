/** Skills tree store — fetches tree and learner states from the backend. */

import { createResource, createSignal } from "solid-js";
import { apiFetch } from "../lib/api";

export interface SkillNode {
  id: string
  domain: string
  name: string
  description: string
  bloomLevel: string
  difficulty: number
  parentSkillId: string
  status: string
  source: string
  treeVersion: number
}

export interface SkillEdge {
  skillId: string
  prereqId: string
  edgeType: string
}

export interface LearnerState {
  skillId: string
  alpha: number
  beta: number
  pMastery: number
  statusEnum: string
  retrievability: number | null
  stability: number | null
  difficulty: number | null
  reps: number
  lapses: number
  lastReview: string | null
  nextReview: string | null
  scaffoldingLevel: number
}

export const [selectedSkillId, setSelectedSkillId] = createSignal<string>("");

export interface TreeData {
  skills: SkillNode[]
  edges: SkillEdge[]
  treeVersion: number
  states: Record<string, LearnerState>
}

export const [tree] = createResource(async () => {
  const data = await apiFetch<TreeData>("/api/skills/tree");
  return data;
});

export const [learnerState, { refetch: refetchState }] = createResource(
  () => selectedSkillId(),
  async (skillId: string) => {
    if (!skillId) return null;
    return apiFetch<LearnerState>(`/api/skills/${skillId}/state`);
  },
);

export function masteryFor(skillId: string): number {
  return tree()?.states?.[skillId]?.pMastery ?? 0;
}

export function getMasteryLabel(p: number): string {
  if (p >= 0.95) return "mastered";
  if (p >= 0.80) return "proficient";
  if (p >= 0.60) return "developing";
  if (p > 0) return "emerging";
  return "not_seen";
}

export function getStatusColor(p: number): string {
  if (p >= 0.95) return "#cccccc";  // mastered — brightest
  if (p >= 0.80) return "#a8a8a8";  // proficient
  if (p >= 0.60) return "#7a7a7a";  // developing
  if (p > 0) return "#555555";      // emerging
  return "#2b2b2b";                 // not_seen — near-background
}
