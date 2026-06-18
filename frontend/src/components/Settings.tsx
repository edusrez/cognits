import { Show, For, createMemo } from "solid-js"
import { linkingMode, linkedViewport } from "../stores/settings-store"
import { getViewportData } from "../stores/viewport-tree-store"
import { type ViewportId, tabKind, dynamicPayload } from "../tabs"

import "./settings/sections" // auto-registers sections via side-effect
import { getMatchingSections } from "../lib/settings-sections"

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
  // instance-specific fields: tabId + scoped (from props/linked viewport) and
  // pdfPath (a reactive accessor so registry sections update when the linked
  // PDF changes without re-running render()).
  const sectionCtx = createMemo(() => ({
    linkedViewport: !!linkedViewport(),
    tabId: linkedActiveTabId(),
    scoped: scopedTabId() !== null,
    pdfPath,
  }))

  const sections = createMemo(() => getMatchingSections(sectionCtx()))

  return (
    <div class="p-3 flex flex-col gap-3 text-[13px]">
      <Show when={linkingMode()}>
        <p class="text-[#9a9a9a]">Click on a viewport to link it.</p>
      </Show>

      {/* ── Registry-driven sections ── */}
      <For each={sections()}>
        {(section) => section.render(sectionCtx())}
      </For>
    </div>
  )
}
