/** Study plan store — fetches plans from the backend. */

import { createResource } from "solid-js";
import { apiFetch } from "../lib/api";

export interface StudyPlan {
  id: string
  sessionId: string
  treeVersion: number
  goal: string
  status: string
  createdAt: string
  updatedAt: string
}

export interface StudyPlanItem {
  id: string
  planId: string
  skillId: string
  mode: string
  status: string
  orderIndex: number
  estimatedDurationMin: number | null
  actualDurationMin: number | null
  learningSessionId: string | null
}

async function fetchActivePlan() {
  try {
    // Fetch all sessions to find plans — the backend doesn't have a /api/study-plans endpoint.
    // Study plans are loaded via the skills tree + plan_study tool.
    // For now, return empty — plans are created on-demand by the study_planner.
    return null as StudyPlan | null;
  } catch {
    return null;
  }
}

export const [activePlan] = createResource(fetchActivePlan);
