import { createSignal } from "solid-js"
import type { ViewportId } from "../tabs"

export interface DragState {
  isDragging: boolean
  tabId: string
  tabLabel: string
  sourceViewport: ViewportId
  targetViewport: ViewportId | null
  insertIndex: number
  mouseX: number
  mouseY: number
}

const initialState: DragState = {
  isDragging: false,
  tabId: "",
  tabLabel: "",
  sourceViewport: "",
  targetViewport: null,
  insertIndex: -1,
  mouseX: 0,
  mouseY: 0,
}

const [dragState, setDragState] = createSignal<DragState>({ ...initialState })

export { dragState }

export function startDrag(
  tabId: string,
  tabLabel: string,
  sourceViewport: ViewportId,
  x: number,
  y: number,
) {
  setDragState({
    isDragging: true,
    tabId,
    tabLabel,
    sourceViewport,
    targetViewport: null,
    insertIndex: -1,
    mouseX: x,
    mouseY: y,
  })
}

export function updateDragPosition(x: number, y: number) {
  setDragState((prev) => ({ ...prev, mouseX: x, mouseY: y }))
}

export function setDragTarget(vpId: ViewportId | null, insertIndex: number) {
  setDragState((prev) => ({ ...prev, targetViewport: vpId, insertIndex }))
}

export function endDrag() {
  setDragState({ ...initialState })
}

interface PendingDrag {
  tabId: string
  tabLabel: string
  sourceViewport: ViewportId
  startX: number
  startY: number
}

let pending: PendingDrag | null = null

export function initiateTabDrag(
  tabId: string,
  tabLabel: string,
  sourceViewport: ViewportId,
  e: MouseEvent,
  onClick: () => void,
) {
  e.preventDefault()
  pending = {
    tabId,
    tabLabel,
    sourceViewport,
    startX: e.clientX,
    startY: e.clientY,
  }

  const onMove = (ev: MouseEvent) => {
    if (!pending) return
    const dx = ev.clientX - pending.startX
    const dy = ev.clientY - pending.startY
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
      const p = pending
      pending = null
      document.removeEventListener("mousemove", onMove)
      document.removeEventListener("mouseup", onUp)
      startDrag(p.tabId, p.tabLabel, p.sourceViewport, ev.clientX, ev.clientY)
    }
  }

  const onUp = () => {
    if (pending) {
      pending = null
      onClick()
    }
    document.removeEventListener("mousemove", onMove)
    document.removeEventListener("mouseup", onUp)
  }

  document.addEventListener("mousemove", onMove)
  document.addEventListener("mouseup", onUp)
}
