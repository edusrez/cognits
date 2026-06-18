import { createEffect, createMemo, Show, createSignal, onCleanup, onMount } from "solid-js"
import {
  rootId,
  getViewportData,
  getViewportIds,
  getSplitData,
  setFraction,
  moveTab,
  placeSessionTabs,
  removeSessionTabs,
  activateTab,
  swapAdjacentTabs,
  removeDynamicTab,
  focusedViewportId,
  setFocusedViewportId,
  shiftHeld,
  setShiftHeld,
  computeViewportPositions,
  findSpatialNeighbor,
  setAllSettingsTabLabels,
  type ViewportId,
} from "./stores/viewport-tree-store"
import { dragState, endDrag, listDragState, endListDrag, moveHint, setMoveHint } from "./drag/drag-state"
import { activeSessionId, setActiveSessionId, deleteSession, setRenamingSessionId } from "./stores/session-store"
import { loadConfig, defaultChatViewport, defaultWriteViewport, defaultLearnitViewport, loadSessionConfig, linkingMode, confirmLinkViewport, cancelLinking, linkedViewport } from "./stores/settings-store"
import { loadSessionMessages } from "./stores/chat-store"
import { initDesktops, createDesktop, switchDesktop, closeDesktop, desktopCount, activeDesktopIndex } from "./stores/desktop-store"
import Viewport from "./components/Viewport"
import DragOverlay, { ListDragOverlay } from "./components/DragOverlay"
import { isDynamicTab, tabDisplayName, tabKind } from "./tabs"

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
  const [spaceHeld, setSpaceHeld] = createSignal(false)

  interface MoveMode {
    itemId: string
    listId: "sessions" | "notebook"
    originalIndex: number
    offset: number
    listLength: number
  }
  const [moveMode, setMoveMode] = createSignal<MoveMode | null>(null)
  let _selectedEl: HTMLElement | null = null

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

  // Keep every base "settings" tab label in sync with the linked viewport's
  // active tab. Lives at App scope (not inside the Settings component) so it
  // never goes stale when Settings unmounts while another tab is active.
  createEffect(() => {
    const linked = linkedViewport()
    const linkedTabId = linked ? getViewportData(linked)?.activeTabId ?? null : null
    const tabLabel = tabDisplayName(linkedTabId)
    const label = tabLabel && tabKind(linkedTabId) !== "settings"
      ? `Settings (${tabLabel})`
      : "Settings"
    setAllSettingsTabLabels(label)
  })

  const handleMoveKey = () => {
    const mm = moveMode()
    if (mm) {
      const targetIndex = mm.originalIndex + mm.offset
      setMoveMode(null)
      setMoveHint(null)
      if (mm.listId === "sessions") {
        import("./stores/session-store").then((m) => m.moveSession(mm.itemId, targetIndex))
      } else {
        import("./stores/notebook-store").then((m) => m.moveNote(mm.itemId, targetIndex))
      }
      return
    }
    if (!_selectedEl) return
    const sid = _selectedEl.getAttribute("data-session-id")
    const nid = _selectedEl.getAttribute("data-note-id")
    const id = sid || nid
    if (!id) return
    const listId: "sessions" | "notebook" = sid ? "sessions" : "notebook"
    const listEl = _selectedEl.closest("[data-list-id]")
    const items = listEl?.querySelectorAll("[data-drag-item]")
    const allIds = Array.from(items ?? []).map(
      (el) => el.getAttribute(sid ? "data-session-id" : "data-note-id") ?? "",
    )
    const idx = allIds.indexOf(id)
    if (idx >= 0) {
      setMoveMode({ itemId: id, listId, originalIndex: idx, offset: 0, listLength: allIds.length })
      setMoveHint({ listId, itemId: id, targetIndex: idx })
    }
  }

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

    function setSelection(el: HTMLElement | null) {
      if (_selectedEl) _selectedEl.classList.remove("keyboard-selected")
      _selectedEl = el
      if (el) el.classList.add("keyboard-selected")
    }
    const handler = (e: KeyboardEvent) => {
      // Space tracking — held while pressing an arrow to reorder tabs.
      if (e.key === " " && !e.repeat) {
        const tag = (e.target as HTMLElement).tagName
        if (tag !== "INPUT" && tag !== "TEXTAREA") {
          e.preventDefault()
          setSpaceHeld(true)
          return
        }
      }
      // Shift tracking — shows viewport highlight while held.
      if (e.key === "Shift" && !e.repeat) {
        const tag = (e.target as HTMLElement).tagName
        if (tag !== "INPUT" && tag !== "TEXTAREA") {
          setShiftHeld(true)
          return
        }
      }

      // Cancel move mode on any key except arrows/m.
      if (moveMode() && !e.repeat && e.key !== "ArrowUp" && e.key !== "ArrowDown" && e.key !== "m") {
        setMoveMode(null)
        setMoveHint(null)
      }

      // Application-level shortcuts — fire regardless of focus.
      if (!e.ctrlKey && !e.shiftKey && !e.altKey) {
        if (e.key === "Enter" && spaceHeld() && _selectedEl && !e.repeat) {
          const tag = (e.target as HTMLElement).tagName
          if (tag !== "INPUT" && tag !== "TEXTAREA") {
            e.preventDefault()
            const el = _selectedEl
            setSelection(null)
            if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
              el.focus?.({ focusVisible: true } as FocusOptions)
            } else {
              const sid = el.getAttribute("data-session-id")
              const nid = el.getAttribute("data-note-id")
              if (sid) {
                setActiveSessionId(activeSessionId() === sid ? null : sid)
              } else if (nid) {
                import("./stores/notebook-store").then((m) =>
                  m.openNoteInViewport(defaultLearnitViewport(), nid),
                )
              } else {
                el.click?.()
              }
            }
          }
          return
        }
      }
      // Link-viewport mode — Space+Arrow moves viewport highlight, Enter confirms.
      if (!e.ctrlKey && !e.shiftKey && !e.altKey && linkingMode() && spaceHeld()) {
        if (e.key === "Enter") {
          const cur = focusedViewportId()
          if (cur) { e.preventDefault(); confirmLinkViewport(cur) }
          return
        }
        if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "ArrowUp" || e.key === "ArrowDown") {
          const cur = focusedViewportId()
          if (cur) {
            const dir = e.key === "ArrowLeft" ? "left"
              : e.key === "ArrowRight" ? "right"
              : e.key === "ArrowUp" ? "up" : "down"
            const neighbor = findSpatialNeighbor(cur, dir, computeViewportPositions())
            if (neighbor) { e.preventDefault(); setFocusedViewportId(neighbor) }
          }
          return
        }
      }
      // Space shortcuts — fire regardless of focus.
      if (spaceHeld() && !e.repeat) {
        if (e.key === "d" && _selectedEl) {
          const sid = _selectedEl.getAttribute("data-session-id")
          if (sid) { e.preventDefault(); setSelection(null); deleteSession(sid); return }
          const rid = _selectedEl.getAttribute("data-report-id")
          if (rid) {
            e.preventDefault(); setSelection(null)
            fetch(`/api/reports/${rid}`, { method: "DELETE" })
              .then(() => import("./stores/learnit-store").then((m) => m.refetchReports()))
            return
          }
          const nid = _selectedEl.getAttribute("data-note-id")
          if (nid) {
            e.preventDefault(); setSelection(null)
            import("./stores/notebook-store").then((m) => m.deleteNote(nid))
            return
          }
        }
        if (e.key === "c") {
          const vpId = focusedViewportId()
          if (vpId) {
            const vp = getViewportData(vpId)
            const tabId = vp?.activeTabId
            if (tabId && isDynamicTab(tabId)) {
              e.preventDefault()
              removeDynamicTab(vpId, tabId)
            }
          }
          return
        }
        if (e.key === "m") {
          handleMoveKey()
          return
        }
        if (e.key === "r" && _selectedEl) {
          const sid = _selectedEl.getAttribute("data-session-id")
          if (sid) {
            e.preventDefault()
            setSelection(null)
            setRenamingSessionId(sid)
          }
          return
        }
      }
      if (e.ctrlKey && !e.shiftKey && !e.altKey) {
        if (e.key === "Enter") {
          const tag = (e.target as HTMLElement).tagName
          if (tag === "INPUT" || tag === "TEXTAREA") {
            e.preventDefault()
            const el = e.target as HTMLElement
            el.blur()
            setSelection(null)
          }
          return
        }
      }
      if (e.shiftKey && !e.ctrlKey && !e.altKey) {
        if (
          e.key === "ArrowLeft" ||
          e.key === "ArrowRight" ||
          e.key === "ArrowUp" ||
          e.key === "ArrowDown"
        ) {
          const current = focusedViewportId()
          if (current) {
            const positions = computeViewportPositions()
            const dir = e.key === "ArrowLeft" ? "left"
              : e.key === "ArrowRight" ? "right"
              : e.key === "ArrowUp" ? "up" : "down"
            const neighbor = findSpatialNeighbor(current, dir, positions)
            if (neighbor) {
              e.preventDefault()
              setFocusedViewportId(neighbor)
            }
          }
          return
        }
        if (e.key === "N") {
          e.preventDefault()
          closeDesktop(activeDesktopIndex())
          return
        }
      }

      // Bare-key shortcuts — blocked on form elements.
      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return

      if (!e.ctrlKey && !e.shiftKey && !e.altKey) {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          const mm = moveMode()
          if (mm) {
            e.preventDefault()
            const delta = e.key === "ArrowUp" ? -1 : 1
            const newOffset = mm.offset + delta
            const targetIdx = mm.originalIndex + newOffset
            if (targetIdx >= 0 && targetIdx < mm.listLength) {
              setMoveMode({ ...mm, offset: newOffset })
              setMoveHint({ listId: mm.listId, itemId: mm.itemId, targetIndex: targetIdx })
            }
            return
          }
          const vpId = focusedViewportId()
          if (vpId) {
            if (spaceHeld()) {
              e.preventDefault()
              const vpEl = document.querySelector(`[data-viewport-id="${vpId}"]`)
              if (vpEl) {
                const items = getFocusableElements(vpEl as HTMLElement)
                if (items.length > 0) {
                  const cur = _selectedEl || (document.activeElement as HTMLElement)
                  let idx = items.indexOf(cur)
                  if (idx < 0) idx = e.key === "ArrowDown" ? -1 : items.length
                  const next = e.key === "ArrowDown"
                    ? (idx + 1) % items.length
                    : (idx - 1 + items.length) % items.length
                  setSelection(items[next])
                  items[next].scrollIntoView?.({ block: "nearest" })
                }
              }
              return
            }
            const el = document.querySelector(`[data-viewport-id="${vpId}"]`)
            if (el) {
              let scrollable: HTMLElement | null = el.querySelector("[data-scrollable]")
              if (!scrollable || (scrollable as HTMLElement).scrollHeight <= (scrollable as HTMLElement).clientHeight) {
                scrollable = null
                const candidates = el.querySelectorAll(".overflow-auto, .overflow-y-auto")
                for (const c of candidates) {
                  const h = c as HTMLElement
                  if (h.scrollHeight > h.clientHeight) { scrollable = h; break }
                }
              }
              if (scrollable) {
                e.preventDefault()
                scrollable.scrollBy({
                  top: e.key === "ArrowDown" ? 60 : -60,
                  behavior: "smooth",
                })
              }
            }
          }
        }
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          const vpId = focusedViewportId()
          if (vpId) {
            if (spaceHeld()) {
              const vp = getViewportData(vpId)
              if (vp && vp.activeTabId) {
                e.preventDefault()
                swapAdjacentTabs(vpId, vp.activeTabId, e.key === "ArrowRight")
              }
              return
            }
            const vp = getViewportData(vpId)
            if (vp) {
              const vis = vp.tabs.filter((t) => !t.hidden || activeSessionId() !== null)
              if (vis.length === 0) return
              const idx = vis.findIndex((t) => t.id === vp.activeTabId)
              const next = e.key === "ArrowRight"
                ? (idx + 1) % vis.length
                : (idx - 1 + vis.length) % vis.length
              e.preventDefault()
              activateTab(vpId, vis[next].id)
            }
          }
        }
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
    }
    document.addEventListener("keydown", handler)
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === " ") { setSpaceHeld(false); setSelection(null); setMoveMode(null); setMoveHint(null); if (linkingMode()) cancelLinking() }
      if (e.key === "Shift") { setShiftHeld(false) }
    }
    document.addEventListener("keyup", onKeyUp)
    const onMouseDown = () => {
      if (moveMode()) { setMoveMode(null); setMoveHint(null) }
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

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  const selector = [
    "button:not([disabled])",
    "[href]",
    "input:not([disabled]):not([type=\"hidden\"])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex=\"-1\"])",
    "select:not([disabled])",
    "[contenteditable=\"true\"]",
    "[class~=\"cursor-pointer\"]",
  ].join(", ")
  return Array.from(container.querySelectorAll(selector)).filter(
    (el) => {
      const s = getComputedStyle(el as HTMLElement)
      return s.display !== "none" && s.visibility !== "hidden"
    },
  ) as HTMLElement[]
}
