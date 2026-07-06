/** Skills tree component — renders the DAG as a parent-tree with mastery indicators. */

import { For, Show, createMemo } from "solid-js";
import type { SkillNode } from "../stores/skills-store";
import {
  tree,
  selectedSkillId,
  setSelectedSkillId,
  learnerState,
  getStatusColor,
  masteryFor,
} from "../stores/skills-store";

interface FlatNode {
  skill: SkillNode
  depth: number
}

export default function SkillsTree() {
  const skills = createMemo(() => tree()?.skills || []);

  // Build a parent-tree: roots have no parentSkillId; children matched by
  // parentSkillId. Orphans (parentSkillId not in skill set) are rendered at
  // root level. The result is flattened for <For> rendering with depth info.
  const flatNodes = createMemo(() => {
    const all = skills();
    const skillMap = new Map<string, SkillNode>();
    for (const s of all) skillMap.set(s.id, s);

    // Group children by parent
    const childrenMap = new Map<string, SkillNode[]>();
    const roots: SkillNode[] = [];

    for (const s of all) {
      const pid = s.parentSkillId;
      if (!pid || !skillMap.has(pid)) {
        roots.push(s);
      } else {
        if (!childrenMap.has(pid)) childrenMap.set(pid, []);
        childrenMap.get(pid)!.push(s);
      }
    }

    // Sort children by name for stability
    for (const [, kids] of childrenMap) {
      kids.sort((a, b) => a.name.localeCompare(b.name));
    }
    roots.sort((a, b) => a.name.localeCompare(b.name));

    // Flatten via BFS preserving parent-child order
    const result: FlatNode[] = [];
    function walk(list: SkillNode[], depth: number) {
      for (const s of list) {
        result.push({ skill: s, depth });
        walk(childrenMap.get(s.id) || [], depth + 1);
      }
    }
    walk(roots, 0);
    return result;
  });

  return (
    <div class="p-4 text-sm overflow-auto h-full">
      <h2 class="text-lg font-bold mb-4">Skills Tree</h2>
      <div class="space-y-0.5">
        <For each={flatNodes()}>
          {(node) => (
            <button
              class="block w-full text-left px-3 py-1.5 rounded border border-gray-800 hover:border-gray-600 transition-colors text-xs"
              style={{ "padding-left": `${8 + node.depth * 16}px` }}
              classList={{
                "border-[#888] bg-[#2a2a2a]": selectedSkillId() === node.skill.id,
              }}
              onClick={() => setSelectedSkillId(node.skill.id)}
            >
              <div class="flex items-center justify-between">
                <span class="truncate">{node.skill.name}</span>
                <span
                  class="inline-block w-2.5 h-2.5 shrink-0 border border-gray-600"
                  style={{ "background-color": getStatusColor(masteryFor(node.skill.id)) }}
                />
              </div>
              <Show when={node.skill.description}>
                <p class="text-gray-500 mt-0.5 truncate">{node.skill.description}</p>
              </Show>
            </button>
          )}
        </For>
      </div>

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
