/** Mastery dashboard — overview of all learner states. */

import { For, createMemo } from "solid-js";
import { tree, getMasteryLabel, getStatusColor } from "../stores/skills-store";

export default function MasteryDashboard() {
  const skills = createMemo(() => tree()?.skills || []);

  const counts = createMemo(() => {
    const c: Record<string, number> = {
      mastered: 0,
      proficient: 0,
      developing: 0,
      emerging: 0,
      not_seen: 0,
    };
    for (const s of skills()) {
      // Without individual learner states loaded, show tree overview
      c.not_seen++;
    }
    return c;
  });

  return (
    <div class="p-4 text-sm overflow-auto h-full">
      <h2 class="text-lg font-bold mb-4">Mastery Dashboard</h2>
      <p class="text-gray-500 mb-4">
        Select a skill in the Skills Tree to view detailed learner state.
      </p>
      <div class="grid grid-cols-2 gap-2">
        <For each={Object.entries(counts())}>
          {([level, count]) => (
            <div class="p-3 rounded border border-gray-700 bg-gray-900/50">
              <div class="text-xs text-gray-400 capitalize">{level.replace("_", " ")}</div>
              <div class="text-lg font-bold">{count}</div>
            </div>
          )}
        </For>
      </div>
      <div class="mt-6">
        <h3 class="font-semibold mb-2">All Skills</h3>
        <div class="space-y-1 max-h-96 overflow-y-auto">
          <For each={skills()}>
            {(skill) => (
              <div class="flex items-center justify-between px-3 py-1.5 rounded bg-gray-900/30 text-xs">
                <span>{skill.name}</span>
                <span class="text-gray-500">{skill.domain || "general"}</span>
              </div>
            )}
          </For>
        </div>
      </div>
    </div>
  );
}
