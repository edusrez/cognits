import { createMemo, Show, Switch, Match } from "solid-js"
import { Dynamic } from "solid-js/web"
import type { ViewportData } from "../stores/viewport-tree-store"
import { activateTab, splitViewport, deleteViewport, canDeleteViewport, ctxMenu, setCtxMenu, removeDynamicTab, setFocusedViewportId, focusedViewportId, shiftHeld } from "../stores/viewport-tree-store"
import { tabs, type ViewportId, baseTabId, tabKind, dynamicPayload } from "../tabs"
import { getSettingsScope } from "../lib/settings-sections"
import { dragState, initiateTabDrag } from "../drag/drag-state"
import { activeSessionId } from "../stores/session-store"
import { linkingMode, hiddenBasicTabs } from "../stores/settings-store"
import ContextMenu from "./ContextMenu"
import TabBar from "./TabBar"

export default function Viewport(props: {
  id: ViewportId
  data: ViewportData
  style?: string
  children?: any
}) {
  const ds = () => dragState()

  const visibleTabs = createMemo(() => {
    const base = props.data.tabs.filter(
      (t) =>
        (!t.hidden || activeSessionId() !== null) &&
        !hiddenBasicTabs().has(t.id),
    )
    if (!ds().isDragging) return base
    return base.filter((t) => t.id !== ds().tabId)
  })

  const visibleActiveTabId = createMemo(() => {
    const vt = visibleTabs()
    const pickVisible = (id: string | null) =>
      id && vt.some((t) => t.id === id) ? id : vt[0]?.id ?? null

    if (!ds().isDragging) return pickVisible(props.data.activeTabId)
    if (ds().tabId === props.data.activeTabId) return vt[0]?.id ?? null
    return pickVisible(props.data.activeTabId)
  })

  const isDragTarget = createMemo(
    () => ds().isDragging && ds().targetViewport === props.id,
  )

  const draggedTabDef = createMemo(() => {
    if (!ds().isDragging) return null
    return tabs.find((t) => t.id === ds().tabId) ?? null
  })

  let textTarget: HTMLInputElement | HTMLTextAreaElement | null = null

  const onContextMenu = (e: MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const target = e.target as HTMLElement
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") {
      textTarget = target as HTMLInputElement | HTMLTextAreaElement
      setCtxMenu({ kind: "text-input", vpId: props.id, x: e.clientX, y: e.clientY })
    } else {
      setCtxMenu({ kind: "viewport", vpId: props.id, x: e.clientX, y: e.clientY })
    }
  }

  const handleCopy = () => {
    setCtxMenu(null)
    if (!textTarget) return
    const start = textTarget.selectionStart ?? 0
    const end = textTarget.selectionEnd ?? 0
    const selected = textTarget.value.slice(start, end)
    if (selected) {
      navigator.clipboard.writeText(selected)
    }
    textTarget = null
  }

  const handlePaste = async () => {
    setCtxMenu(null)
    if (!textTarget) return
    const input = textTarget
    textTarget = null
    try {
      const text = await navigator.clipboard.readText()
      const start = input.selectionStart ?? 0
      const end = input.selectionEnd ?? 0
      input.value = input.value.slice(0, start) + text + input.value.slice(end)
      const newPos = start + text.length
      input.selectionStart = input.selectionEnd = newPos
      input.focus()
    } catch {
      // clipboard access denied, silently ignore
    }
  }

  const vpMenu = createMemo(() => {
    const m = ctxMenu()
    if (!m) return null
    if ((m.kind === "viewport" || m.kind === "text-input" || m.kind === "tab") && m.vpId === props.id) return m
    return null
  })

  return (
    <div
      data-viewport-id={props.id}
      class="flex flex-col h-full"
      classList={{ "viewport-linking": linkingMode(), "viewport-keyboard-active": (shiftHeld() || linkingMode()) && focusedViewportId() === props.id }}
      style={props.style}
      onContextMenu={onContextMenu}
      onClick={() => setFocusedViewportId(props.id)}
    >
      <Show when={visibleTabs().length > 0 || isDragTarget()}>
        <TabBar
          tabs={visibleTabs()}
          activeTabId={visibleActiveTabId()}
          onCloseTab={(tabId) => {
            removeDynamicTab(props.id, tabId)
            if (tabKind(tabId) === "report") {
              const reportId = dynamicPayload(tabId) ?? ""
              import("../stores/report-store").then((m) => {
                if (m.removeReportData) m.removeReportData(reportId)
              })
            }
          }}
          onTabDragStart={(tabId, label, e) => {
            initiateTabDrag(tabId, label, props.id, e, () =>
              activateTab(props.id, tabId),
            )
          }}
          isDragTarget={isDragTarget()}
          draggedTabId={ds().tabId}
          draggedTabLabel={ds().tabLabel}
          dragInsertIndex={ds().insertIndex}
        />
      </Show>
      <div data-scrollable class="flex-1 overflow-auto relative">
        <Switch fallback={props.children}>
          <Match when={isDragTarget() && draggedTabDef()}>
            <div class="viewport-dimmed-content">
              <Dynamic component={draggedTabDef()!.component} />
            </div>
          </Match>
          <Match when={visibleActiveTabId()}>
            {(activeId) => {
              const tab = createMemo(() => tabs.find((t) => t.id === baseTabId(activeId())))
              return (
                <Show when={tab()} fallback={null}>
                  {(t) => <Dynamic component={t().component} viewportId={props.id} tabId={activeId()} />}
                </Show>
              )
            }}
          </Match>
        </Switch>
      </div>

        <Show when={vpMenu()}>
          {(m) => (
            <Show
              when={m().kind === "text-input"}
              fallback={
                <Show
                  when={m().kind === "tab"}
                  fallback={
                    <ContextMenu
                      x={m().x}
                      y={m().y}
                      onClose={() => setCtxMenu(null)}
                      items={[
                        { label: "Split horizontally",  onClick: () => { setCtxMenu(null); splitViewport(props.id, "h") } },
                        { label: "Split vertically",    onClick: () => { setCtxMenu(null); splitViewport(props.id, "v") } },
                        { label: "Delete viewport",     onClick: () => { setCtxMenu(null); deleteViewport(props.id) }, class: canDeleteViewport(props.id) ? "text-red-400" : "text-[#4a4a4a]" },
                      ]}
                    />
                  }
                >
                  <ContextMenu
                    x={m().x}
                    y={m().y}
                    onClose={() => setCtxMenu(null)}
                    items={[
                      {
                        label: `Open Settings (${(m() as any).tabLabel})`,
                        onClick: () => {
                          const tabMenu = m() as any
                          setCtxMenu(null)
                          const tabId = `settings:${getSettingsScope(tabMenu.tabId)}`
                          const label = `Settings (${tabMenu.tabLabel})`
                          import("../stores/viewport-tree-store").then((vts) => {
                            vts.addDynamicTab(props.id, { id: tabId, label, hidden: false })
                          })
                        },
                      },
                    ]}
                  />
                </Show>
              }
            >
              <ContextMenu
                x={m().x}
                y={m().y}
                onClose={() => { setCtxMenu(null); textTarget = null }}
                items={[
                  { label: "Copy",  onClick: handleCopy },
                  { label: "Paste", onClick: handlePaste },
                ]}
              />
            </Show>
          )}
        </Show>
    </div>
  )
}
