import { Show, For, createMemo } from "solid-js"
import {
  linkingMode,
  beginLinking,
  linkedViewport,
  hiddenBasicTabs,
  toggleBasicTab,
} from "../stores/settings-store"
import { getViewportData, resetTree } from "../stores/viewport-tree-store"
import { type ViewportId, tabKind, dynamicPayload } from "../tabs"
import CollapsibleSection from "./CollapsibleSection"

import "./settings/sections" // auto-registers sections via side-effect
import { getMatchingSections } from "../lib/settings-sections"

const basicTabs = [
  { id: "files", label: "Files" },
  { id: "sessions", label: "Sessions" },
] as const

export default function Settings(props: { viewportId?: ViewportId; tabId?: string }) {
  const scopedTabId = createMemo(() => {
    const t = props.tabId || ""
    return tabKind(t) === "settings" ? dynamicPayload(t) : null
  })

  const linkedActiveTabId = createMemo(() => {
    if (scopedTabId()) return scopedTabId()
    const vp = linkedViewport()
    if (!vp) return null
    return getViewportData(vp)?.activeTabId ?? null
  })

  const pdfPath = createMemo(() => {
    const tabId = linkedActiveTabId()
    if (tabId && tabKind(tabId) === "pdf") return dynamicPayload(tabId)
    return null
  })

  // Per-instance context shared by matches() and render(). The shell owns the
  // instance-specific fields: tabId (from props/linked viewport) and pdfPath
  // (a reactive accessor so registry sections update when the linked PDF
  // changes without re-running render()).
  const sectionCtx = createMemo(() => ({
    linkedViewport: !!linkedViewport(),
    tabId: linkedActiveTabId(),
    pdfPath,
  }))

  const sections = createMemo(() => getMatchingSections(sectionCtx()))

  return (
    <div class="p-3 flex flex-col gap-3 text-[13px]">
      <Show when={!linkedViewport() && !scopedTabId()}>
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
      </Show>

      <Show when={linkingMode()}>
        <p class="text-[#9a9a9a]">Click on a viewport to link it.</p>
      </Show>

      {/* ── Registry-driven sections ── */}
      <For each={sections()}>
        {(section) => section.render(sectionCtx())}
      </For>

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

          <Show when={linkedViewport() && !scopedTabId()}>
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
    </div>
  )
}
