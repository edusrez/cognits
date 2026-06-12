import { createEffect, createMemo, Show, createSignal, onCleanup, onMount } from "solid-js"
import {
  rootId,
  getViewportData,
  getSplitData,
  setFraction,
  moveTab,
  placeSessionTabs,
  removeSessionTabs,
  type ViewportId,
} from "./stores/viewport-tree-store"
import { dragState, endDrag } from "./drag/drag-state"
import { activeSessionId } from "./stores/session-store"
import { loadConfig, defaultChatViewport, defaultWriteViewport, loadSessionConfig } from "./stores/settings-store"
import { loadSessionMessages } from "./stores/chat-store"
import { initDesktops, createDesktop, switchDesktop, closeDesktop, desktopCount, activeDesktopIndex } from "./stores/desktop-store"
import Viewport from "./components/Viewport"
import DragOverlay from "./components/DragOverlay"

initDesktops()

export default function App() {
  createEffect(() => {
    const sid = activeSessionId()
    if (sid) {
      placeSessionTabs(defaultChatViewport(), defaultWriteViewport())
      loadSessionMessages(sid)
      loadSessionConfig(sid)
    } else {
      removeSessionTabs()
    }
  })

  const handleDrop = () => {
    const ds = dragState()
    if (ds.targetViewport !== null) {
      moveTab(ds.tabId, ds.sourceViewport, ds.targetViewport, ds.insertIndex)
    }
    endDrag()
  }

  onCleanup(() => {
    endDrag()
  })

  onMount(() => {
    loadConfig()
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return

      if (!e.ctrlKey && !e.shiftKey && !e.altKey) {
        if (e.key === "n") {
          e.preventDefault()
          createDesktop()
          return
        }
        const num = parseInt(e.key)
        if (num >= 1 && num <= 9 && num <= desktopCount()) {
          e.preventDefault()
          switchDesktop(num - 1)
        }
      }
      if (!e.ctrlKey && e.shiftKey && !e.altKey) {
        if (e.key === "N") {
          e.preventDefault()
          closeDesktop(activeDesktopIndex())
        }
      }
    }
    document.addEventListener("keydown", handler)
    onCleanup(() => document.removeEventListener("keydown", handler))
  })

  return (
    <div
      class="h-screen w-screen bg-black text-[#e0e0e0] select-none"
      onContextMenu={(e) => e.preventDefault()}
    >
      <GridNode id={rootId()} />
      <DragOverlay onDrop={handleDrop} />
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
