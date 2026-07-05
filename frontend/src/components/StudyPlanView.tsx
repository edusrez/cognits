/** Study plan view — displays the active learning plan. */

import { Show } from "solid-js";
import { activePlan } from "../stores/study-plan-store";

export default function StudyPlanView() {
  return (
    <div class="p-4 text-sm overflow-auto h-full">
      <h2 class="text-lg font-bold mb-4">Study Plan</h2>
      <Show
        when={activePlan()}
        fallback={
          <p class="text-gray-500">
            No active study plan. Ask the Teacher to create one by saying
            "create a study plan for me."
          </p>
        }
      >
        {(plan) => (
          <div>
            <h3 class="font-semibold mb-2">{plan().goal}</h3>
            <p class="text-gray-500 text-xs mb-4">
              Created: {new Date(plan().createdAt).toLocaleDateString()}
            </p>
          </div>
        )}
      </Show>
    </div>
  );
}
