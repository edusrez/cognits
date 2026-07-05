/** Skills tree component — renders the DAG with mastery badges. */

import { For, Show, createMemo } from "solid-js";
import {
  tree,
  selectedSkillId,
  setSelectedSkillId,
  learnerState,
  getStatusColor,
} from "../stores/skills-store";

export default function SkillsTree() {
  const skills = createMemo(() => tree()?.skills || []);
  const edges = createMemo(() => tree()?.edges || []);

  // Group skills by domain
  const domains = createMemo(() => {
    const map: Record<string, typeof skills> = {};
    for (const s of skills()) {
      const d = s.domain || "general";
      if (!map[d]) map[d] = [];
      map[d].push(s);
    }
    return map;
  });

  return (
    <div class="p-4 text-sm overflow-auto h-full">
      <h2 class="text-lg font-bold mb-4">Skills Tree</h2>
      <For each={Object.entries(domains())}>
        {([domain, domainSkills]) => (
          <div class="mb-4">
            <h3 class="text-base font-semibold text-gray-300 mb-2 capitalize">
              {domain}
            </h3>
            <div class="space-y-1">
              <For each={domainSkills}>
                {(skill) => (
                  <button
                    class="block w-full text-left px-3 py-2 rounded border border-gray-700 hover:border-gray-500 transition-colors text-xs"
                    classList={{
                      "border-blue-500 bg-blue-900/20": selectedSkillId() === skill.id,
                    }}
                    onClick={() => setSelectedSkillId(skill.id)}
                  >
                    <div class="flex items-center justify-between">
                      <span>{skill.name}</span>
                      <span
                        class="inline-block w-2.5 h-2.5 rounded-full"
                        style={{ "background-color": getStatusColor(0) }}
                      />
                    </div>
                    <Show when={skill.description}>
                      <p class="text-gray-500 mt-0.5 truncate">{skill.description}</p>
                    </Show>
                  </button>
                )}
              </For>
            </div>
          </div>
        )}
      </For>

      <Show when={selectedSkillId()}>
        <div class="mt-6 p-4 border border-gray-700 rounded bg-gray-900/50">
          <h3 class="font-semibold mb-2">Learner State</h3>
          <Show
            when={learnerState()}
            fallback={<p class="text-gray-500">Loading...</p>}
          >
            {(state) => (
              <div class="space-y-1 text-xs">
                <p>
                  Mastery: <span class="font-mono">{(state().pMastery * 100).toFixed(0)}%</span>
                </p>
                <p>Status: {state().statusEnum}</p>
                <p>Scaffolding: Lv.{state().scaffoldingLevel}</p>
                <Show when={state().nextReview}>
                  <p>Next review: {state().nextReview}</p>
                </Show>
                <p>
                  Reps: {state().reps} · Lapses: {state().lapses}
                </p>
              </div>
            )}
          </Show>
        </div>
      </Show>
    </div>
  );
}
