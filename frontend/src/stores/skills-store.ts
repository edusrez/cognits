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

export const [tree] = createResource(async () => {
  const data = await apiFetch<{
    skills: SkillNode[]
    edges: SkillEdge[]
    treeVersion: number
  }>("/api/skills/tree");
  return data;
});

export const [learnerState, { refetch: refetchState }] = createResource(
  () => selectedSkillId(),
  async (skillId: string) => {
    if (!skillId) return null;
    return apiFetch<LearnerState>(`/api/skills/${skillId}/state`);
  },
);

export function getMasteryLabel(p: number): string {
  if (p >= 0.95) return "mastered";
  if (p >= 0.80) return "proficient";
  if (p >= 0.60) return "developing";
  if (p > 0) return "emerging";
  return "not_seen";
}

export function getStatusColor(p: number): string {
  if (p >= 0.95) return "#4ade80";  // green
  if (p >= 0.80) return "#a3e635";  // lime
  if (p >= 0.60) return "#facc15";  // yellow
  if (p > 0) return "#fb923c";      // orange
  return "#9ca3af";                 // gray
}
