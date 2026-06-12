import { For, createMemo } from "solid-js"
import type { Tab } from "../stores/viewport-tree-store"
import { setCtxMenu } from "../stores/viewport-tree-store"

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
              {tab.label}
              {!isGhost && (tab.id.startsWith("report:") || tab.id.startsWith("settings:")) && (
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
            </div>
          )
        }}
      </For>
    </div>
  )
}
