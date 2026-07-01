import { For, createMemo } from "solid-js"
import type { Tab } from "../stores/viewport-tree-store"
import { setCtxMenu, baseSettingsTabLabel } from "../stores/viewport-tree-store"
import { isDynamicTab } from "../tabs"
import { currentToolStatus, isThinking, isStreaming, mainSessionPromptTokens } from "../stores/chat-store"

export default function TabBar(props: {
  tabs: Tab[]
  activeTabId: string | null
  onCloseTab?: (tabId: string) => void
  onTabDragStart: (tabId: string, label: string, e: MouseEvent) => void
  isDragTarget: boolean
  draggedTabId: string
  draggedTabLabel: string
  dragInsertIndex: number
}) {
  const displayTabs = createMemo(() => {
    const filtered = props.tabs.filter((t) => t.id !== props.draggedTabId)

    if (!props.isDragTarget) return filtered

    const insertIdx = Math.min(props.dragInsertIndex, filtered.length)
    const result = [...filtered]
    result.splice(insertIdx, 0, {
      id: "__ghost__",
      label: props.draggedTabLabel,
      hidden: false,
    })
    return result
  })

  return (
    <div
      data-tab-bar
      class="flex w-full"
      style={{ "min-height": "28px" }}
    >
      <For each={displayTabs()}>
        {(tab, index) => {
          const isGhost = tab.id === "__ghost__"
          return (
              <div
                data-tab-index={index()}
                data-drag-ghost={isGhost ? "" : undefined}
                class="flex-1 min-w-0 truncate flex items-center justify-center border border-white/10 text-[11px] relative"
                classList={{
                "text-[#e0e0e0]": !isGhost && tab.id === props.activeTabId,
                "text-[#6a6a6a]": !isGhost && tab.id !== props.activeTabId,
                "opacity-40": isGhost,
                "viewport-dimmed-tab": props.isDragTarget && !isGhost,
                "border-r-0": index() < displayTabs().length - 1,
              }}
              style={{
                padding: "4px 8px",
              }}
              onMouseDown={(e) => {
                if (!isGhost) {
                  props.onTabDragStart(tab.id, tab.label, e)
                }
              }}
              onContextMenu={(e) => {
                if (isGhost) return
                e.preventDefault()
                e.stopPropagation()
                const vpEl = (e.currentTarget as HTMLElement).closest("[data-viewport-id]")
                const vpId = vpEl?.getAttribute("data-viewport-id")
                setCtxMenu({
                  kind: "tab",
                  vpId: vpId || "",
                  tabId: tab.id,
                  tabLabel: tab.label,
                  x: e.clientX,
                  y: e.clientY,
                })
              }}
            >
              {tab.id === "chat" ? (
                <div class="grid grid-cols-[1fr_auto_1fr] items-center w-full gap-1 min-w-0">
                  <span class="truncate text-[10px] text-[#5a5a5a]">
                    {Object.entries(currentToolStatus()).map(([agent, status]) => {
                      const cleanStatus = status.endsWith("...") ? status.replace(/\.\.\.$/, "") : status
                      const animated = status.endsWith("...")
                      return `${agent}: ${cleanStatus}${animated ? "" : ""}`
                    }).join(" | ") || (isThinking() ? "Thinking..." : isStreaming() ? "Writing..." : "Ready")}
                  </span>
                  <span class="text-[11px] whitespace-nowrap">{tab.label}</span>
                  <div class="w-10 h-1.5 border border-white/15 justify-self-end">
                    <div
                      class="h-full bg-white/20 transition-[width] duration-300"
                      style={{ width: `${Math.min((mainSessionPromptTokens() / 1_000_000) * 100, 100)}%` }}
                    />
                  </div>
                </div>
              ) : (
                <>
                  {tab.id === "settings" ? baseSettingsTabLabel() : tab.label}
                  {!isGhost && isDynamicTab(tab.id) && (
                    <span
                      class="absolute right-1 hover:text-[#e0e0e0] cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation()
                        props.onCloseTab?.(tab.id)
                      }}
                    >
                      ×
                    </span>
                  )}
                </>
              )}
            </div>
          )
        }}
      </For>
    </div>
  )
}
