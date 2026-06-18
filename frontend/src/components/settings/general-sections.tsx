/** General Settings sections — the link prompt (no viewport linked yet) and
 *  the always-on General block (basic tabs, restore layout, change linked
 *  viewport). The link prompt replaces both the old shell prompt and the
 *  redundant "global" registry section, which showed the same hint twice. */

import { Show, For } from "solid-js"
import { registerSection } from "../../lib/settings-sections"
import CollapsibleSection from "../CollapsibleSection"
import {
  linkingMode,
  beginLinking,
  linkedViewport,
  hiddenBasicTabs,
  toggleBasicTab,
} from "../../stores/settings-store"
import { resetTree } from "../../stores/viewport-tree-store"

const basicTabs = [
  { id: "files", label: "Files" },
  { id: "sessions", label: "Sessions" },
] as const

// ── Link prompt: shown for the base (non-scoped) Settings with no link ──

registerSection({
  id: "settings:link-prompt",
  matches: (ctx) => !ctx.linkedViewport && !ctx.scoped,
  render: () => (
    <>
      <p class="text-[#9a9a9a] leading-relaxed">
        Settings works linked to a viewport to show the specific
        settings for that viewport's active tab.
      </p>
      <div class="flex justify-center">
        <button
          class="border border-white/20 px-3 py-1.5 hover:bg-white/10 transition-colors cursor-pointer w-full"
          onClick={() => beginLinking("viewport")}
        >
          Link Viewport
        </button>
      </div>
    </>
  ),
})

// ── General: always shown (base and scoped instances alike) ──

registerSection({
  id: "general",
  matches: () => true,
  render: (ctx) => (
    <CollapsibleSection title="General Settings">
      <div class="flex flex-col gap-2">
        <div class="text-[#9a9a9a]">Basic tabs</div>
        <For each={basicTabs}>
          {(tab) => {
            const hidden = () => hiddenBasicTabs().has(tab.id)
            return (
              <button
                class="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-white/10 transition-colors cursor-pointer"
                onClick={() => toggleBasicTab(tab.id)}
              >
                <span
                  class="inline-block w-3.5 h-3.5 border border-white/30 shrink-0"
                  classList={{ "bg-white/20": !hidden() }}
                />
                <span class={hidden() ? "text-[#6a6a6a]" : ""}>
                  {tab.label}
                </span>
              </button>
            )
          }}
        </For>

        <div class="mt-1">
          <button
            class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors cursor-pointer w-full text-center"
            onClick={resetTree}
          >
            Restore Default Layout
          </button>
        </div>

        <Show when={ctx.linkedViewport && !ctx.scoped}>
          <div class="flex flex-col items-center gap-2 mt-2">
            <button
              class="border border-white/20 px-3 py-1.5 hover:bg-white/10 transition-colors cursor-pointer w-full"
              onClick={() => beginLinking("viewport")}
              disabled={linkingMode()}
            >
              Change Linked Viewport
            </button>
          </div>
        </Show>
      </div>
    </CollapsibleSection>
  ),
})
