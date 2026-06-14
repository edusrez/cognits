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
  if (e.button !== 0) return
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

// --- list dragging (sessions, notes) ---

export interface ListDragState {
  isDragging: boolean
  itemId: string
  itemLabel: string
  listId: string
  insertIndex: number
  mouseX: number
  mouseY: number
}

const listInitialState: ListDragState = {
  isDragging: false,
  itemId: "",
  itemLabel: "",
  listId: "",
  insertIndex: -1,
  mouseX: 0,
  mouseY: 0,
}

const [listDragState, setListDragState] = createSignal<ListDragState>({
  ...listInitialState,
})

export { listDragState }

export function startListDrag(
  itemId: string,
  itemLabel: string,
  listId: string,
  x: number,
  y: number,
) {
  setListDragState({
    isDragging: true,
    itemId,
    itemLabel,
    listId,
    insertIndex: -1,
    mouseX: x,
    mouseY: y,
  })
}

export function updateListDragPosition(x: number, y: number) {
  setListDragState((prev) => ({ ...prev, mouseX: x, mouseY: y }))
}

export function setListDragInsert(insertIndex: number) {
  setListDragState((prev) => ({ ...prev, insertIndex }))
}

export function endListDrag() {
  setListDragState({ ...listInitialState })
}

export interface MoveHint {
  listId: string
  itemId: string
  targetIndex: number
}

export const [moveHint, setMoveHint] = createSignal<MoveHint | null>(null)

interface PendingListDrag {
  itemId: string
  itemLabel: string
  listId: string
  startX: number
  startY: number
}

let pendingList: PendingListDrag | null = null

export function initiateListDrag(
  itemId: string,
  itemLabel: string,
  listId: string,
  e: MouseEvent,
) {
  if (e.button !== 0) return
  pendingList = {
    itemId,
    itemLabel,
    listId,
    startX: e.clientX,
    startY: e.clientY,
  }

  const onMove = (ev: MouseEvent) => {
    if (!pendingList) return
    const dx = ev.clientX - pendingList.startX
    const dy = ev.clientY - pendingList.startY
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
      const p = pendingList
      pendingList = null
      document.removeEventListener("mousemove", onMove)
      document.removeEventListener("mouseup", onUp)
      startListDrag(p.itemId, p.itemLabel, p.listId, ev.clientX, ev.clientY)
    }
  }

  const onUp = () => {
    pendingList = null
    document.removeEventListener("mousemove", onMove)
    document.removeEventListener("mouseup", onUp)
  }

  document.addEventListener("mousemove", onMove)
  document.addEventListener("mouseup", onUp)
}
