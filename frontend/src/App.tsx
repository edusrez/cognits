import { createEffect, createMemo, on, Show, createSignal, onCleanup, onMount } from "solid-js"
import {
  rootId,
  getViewportData,
  getSplitData,
  setFraction,
  moveTab,
  placeSessionTabs,
  removeSessionTabs,
  setBaseSettingsTabLabel,
  type ViewportId,
} from "./stores/viewport-tree-store"
import { dragState, endDrag, listDragState, endListDrag, moveHint, setMoveHint } from "./drag/drag-state"
import { activeSessionId } from "./stores/session-store"
import { loadConfig, defaultChatViewport, defaultWriteViewport, loadSessionConfig, linkedViewport } from "./stores/settings-store"
import { loadSessionMessages } from "./stores/chat-store"
import { initDesktops } from "./stores/desktop-store"
import Viewport from "./components/Viewport"
import DragOverlay, { ListDragOverlay } from "./components/DragOverlay"
import { tabDisplayName, tabKind } from "./tabs"
import {
  createKeyboardState,
  trackModifierDown,
  trackModifierUp,
} from "./lib/keyboard/state"
import { handleViewportFocus, handleLinkMode, handleArrowNavigation } from "./lib/keyboard/viewport-nav"
import { cancelMoveModeOnKey, handleSpaceEnter, handleSpaceShortcuts, handleCtrlEnter } from "./lib/keyboard/selection-actions"
import { handleDesktopShortcuts } from "./lib/keyboard/desktop-shortcuts"

initDesktops()

const [ragReady, setRagReady] = createSignal(false)
const [ragError, setRagError] = createSignal<string | null>(null)

async function pollHealth() {
  try {
    const res = await fetch("/api/health")
    if (!res.ok) return
    const data = await res.json()
    if (data.rag_error) {
      setRagError(data.rag_error)
      return
    }
    if (data.rag_ready) {
      setRagReady(true)
      return
    }
  } catch {
    // Server not ready yet — retry
  }
  setTimeout(pollHealth, 500)
}

pollHealth()

export default function App() {
  const kb = createKeyboardState()

  // Place/replace session tabs only when the session changes — NOT when the
  // link memos re-resolve (e.g. after a split). Without on(), placeSessionTabs
  // writes viewportMap → link memos re-evaluate → effect re-fires → infinite
  // recursion (too much recursion crash). The memos are read inside the body
  // to get their current resolved value, but only activeSessionId triggers.
  createEffect(on(activeSessionId, (sid) => {
    if (sid) {
      placeSessionTabs(defaultChatViewport(), defaultWriteViewport())
      loadSessionMessages(sid)
      loadSessionConfig(sid)
    } else {
      removeSessionTabs()
    }
  }))

  // Keep the base "settings" tab label in sync with the linked viewport's
  // active tab. Writes to a signal (NOT viewportMap) — writing to the store
  // from an effect that reads it causes infinite recursion (produce notifies
  // all listeners → linkedViewport memo re-evaluates → effect re-fires).
  createEffect(() => {
    const linked = linkedViewport()
    const linkedTabId = linked ? getViewportData(linked)?.activeTabId ?? null : null
    const tabLabel = tabDisplayName(linkedTabId)
    const label = tabLabel && tabKind(linkedTabId) !== "settings"
      ? `Settings (${tabLabel})`
      : "Settings"
    setBaseSettingsTabLabel(label)
  })

  const handleDrop = () => {
    const ds = dragState()
    if (ds.targetViewport !== null) {
      moveTab(ds.tabId, ds.sourceViewport, ds.targetViewport, ds.insertIndex)
    }
    endDrag()
  }

  const handleListDrop = (listId: string, insertIndex: number) => {
    const ds = listDragState()
    if (listId === "sessions") {
      import("./stores/session-store").then((m) => { m.moveSession(ds.itemId, insertIndex); endListDrag() })
    } else if (listId === "notebook") {
      import("./stores/notebook-store").then((m) => { m.moveNote(ds.itemId, insertIndex); endListDrag() })
    }
  }

  onCleanup(() => {
    endDrag()
  })

  onMount(() => {
    loadConfig()

    // Keyboard dispatch — order preserves the original monolithic handler.
    // Global handlers fire regardless of focus; the form-element gate sits
    // between them and the bare-key handlers (which are blocked on inputs).
    const handler = (e: KeyboardEvent) => {
      if (trackModifierDown(e, kb)) return
      cancelMoveModeOnKey(e, kb)
      if (handleSpaceEnter(e, kb)) return
      if (handleLinkMode(e, kb)) return
      if (handleSpaceShortcuts(e, kb)) return
      if (handleCtrlEnter(e, kb)) return
      if (handleViewportFocus(e)) return

      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return

      if (handleArrowNavigation(e, kb)) return
      if (handleDesktopShortcuts(e)) return
    }
    document.addEventListener("keydown", handler)
    const onKeyUp = (e: KeyboardEvent) => trackModifierUp(e, kb)
    document.addEventListener("keyup", onKeyUp)
    const onMouseDown = () => {
      if (kb.moveMode()) { kb.setMoveMode(null); setMoveHint(null) }
    }
    document.addEventListener("mousedown", onMouseDown)
    onCleanup(() => {
      document.removeEventListener("keydown", handler)
      document.removeEventListener("keyup", onKeyUp)
      document.removeEventListener("mousedown", onMouseDown)
    })
  })

  return (
    <div
      class="h-screen w-screen bg-black text-[#e0e0e0] select-none"
      onContextMenu={(e) => e.preventDefault()}
    >
      <Show
        when={ragReady()}
        fallback={
          <div class="h-full w-full flex items-center justify-center">
            <div class="flex flex-col items-center gap-3">
              <div class="text-[#6a6a6a]">
                {ragError() ? `RAG error: ${ragError()}` : "Loading BGE-M3 model..."}
              </div>
              <Show when={!ragError()}>
                <div class="w-48 h-1 border border-white/20">
                  <div class="h-full bg-white/20 animate-pulse" style={{ width: "60%" }} />
                </div>
              </Show>
            </div>
          </div>
        }
      >
        <GridNode id={rootId()} />
        <DragOverlay onDrop={handleDrop} />
        <ListDragOverlay onDrop={handleListDrop} />
      </Show>
    </div>
  )
}

function GridNode(props: { id: ViewportId }) {
  const split = createMemo(() => getSplitData(props.id))
  const leaf = createMemo(() => getViewportData(props.id))

  return (
    <Show when={split()} fallback={
      <Show when={leaf()}>
        {(vp) => (
          <div style={{ width: "100%", height: "100%" }}>
            <Viewport id={props.id} data={vp()} />
          </div>
        )}
      </Show>
    }>
      <SplitView id={props.id} />
    </Show>
  )
}

function SplitView(props: { id: ViewportId }) {
  const split = createMemo(() => getSplitData(props.id)!)
  const children = createMemo(() => split().children)
  const f0 = createMemo(() => split().fractions[0])
  const f1 = createMemo(() => split().fractions[1])
  const isH = createMemo(() => split().direction === "h")
  const [dragging, setDragging] = createSignal(false)

  const onResizerDown = (e: MouseEvent) => {
    e.preventDefault()
    // Capture the container here: during the drag the pointer can leave
    // this split and ev.target would point to another container.
    const gridRef = (e.currentTarget as HTMLElement).closest("[data-split]") as HTMLElement | null
    if (!gridRef) return
    setDragging(true)

    const start = isH() ? e.clientX : e.clientY
    const startF0 = f0()
    const startF1 = f1()
    const totalFr = startF0 + startF1

    const onMove = (ev: MouseEvent) => {
      const current = isH() ? ev.clientX : ev.clientY
      const delta = current - start

      const rect = gridRef.getBoundingClientRect()
      const size = isH() ? rect.width - 4 : rect.height - 4

      if (size <= 0) return
      const p0 = (startF0 * size) / totalFr
      const p1 = Math.max(10, Math.min(size - 10, p0 + delta))
      const clamped = (p1 * totalFr) / size
      setFraction(props.id, 0, Math.max(0.5, clamped))
      setFraction(props.id, 1, Math.max(0.5, totalFr - clamped))
    }

    const onUp = () => {
      setDragging(false)
      document.removeEventListener("mousemove", onMove)
      document.removeEventListener("mouseup", onUp)
    }

    document.addEventListener("mousemove", onMove)
    document.addEventListener("mouseup", onUp)
  }

  return (
    <div
      data-split
      style={{
        display: "grid",
        overflow: "hidden",
        width: "100%",
        height: "100%",
        ...(isH()
          ? {
              "grid-template-columns": `minmax(0, ${f0()}fr) 4px minmax(0, ${f1()}fr)`,
              "grid-template-rows": "minmax(0, 1fr)",
            }
          : {
              "grid-template-columns": "minmax(0, 1fr)",
              "grid-template-rows": `minmax(0, ${f0()}fr) 4px minmax(0, ${f1()}fr)`,
            }),
      }}
    >
      <GridNode id={children()[0]} />
      <div
        class="resizer"
        classList={{ "resizer-dragging": dragging() }}
        style={{ cursor: isH() ? "col-resize" : "row-resize" }}
        onMouseDown={onResizerDown}
      />
      <GridNode id={children()[1]} />
    </div>
  )
}
