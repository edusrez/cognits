import { createEffect, onCleanup, Show } from "solid-js"
import {
  dragState,
  updateDragPosition,
  setDragTarget,
  endDrag,
  listDragState,
  updateListDragPosition,
  setListDragInsert,
  endListDrag,
} from "../drag/drag-state"
import type { ViewportId } from "../tabs"

function calcInsertIndex(vpEl: Element, x: number, y: number): number {
  const tabBar = vpEl.querySelector("[data-tab-bar]")
  if (!tabBar) return 0

  const realTabs = tabBar.querySelectorAll(
    "[data-tab-index]:not([data-drag-ghost])",
  )

  const tabBarRect = tabBar.getBoundingClientRect()
  if (y > tabBarRect.bottom) {
    return realTabs.length
  }

  let insertIdx = 0
  realTabs.forEach((tab, idx) => {
    const rect = tab.getBoundingClientRect()
    if (x > rect.left + rect.width / 2) {
      insertIdx = idx + 1
    }
  })
  return insertIdx
}

function hitTestViewport(
  x: number,
  y: number,
): { vpId: ViewportId | null; insertIndex: number } {
  const vpEls = document.querySelectorAll("[data-viewport-id]")
  for (const el of vpEls) {
    const rect = el.getBoundingClientRect()
    if (
      x >= rect.left &&
      x <= rect.right &&
      y >= rect.top &&
      y <= rect.bottom
    ) {
      const vpId = el.getAttribute("data-viewport-id") as ViewportId
      return { vpId, insertIndex: calcInsertIndex(el, x, y) }
    }
  }
  return { vpId: null, insertIndex: -1 }
}

export default function DragOverlay(props: { onDrop: () => void }) {
  const ds = () => dragState()

  const handleMouseMove = (e: MouseEvent) => {
    updateDragPosition(e.clientX, e.clientY)
    const { vpId, insertIndex } = hitTestViewport(e.clientX, e.clientY)
    setDragTarget(vpId, insertIndex)
  }

  const handleMouseUp = (e: MouseEvent) => {
    updateDragPosition(e.clientX, e.clientY)
    const { vpId, insertIndex } = hitTestViewport(e.clientX, e.clientY)
    setDragTarget(vpId, insertIndex)
    props.onDrop()
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      endDrag()
      props.onDrop()
    }
  }

  createEffect(() => {
    if (ds().isDragging) {
      document.body.classList.add("drag-grabbing")
      document.addEventListener("keydown", handleKeyDown)
      onCleanup(() => {
        document.body.classList.remove("drag-grabbing")
        document.removeEventListener("keydown", handleKeyDown)
      })
    }
  })

  return (
    <Show when={ds().isDragging}>
      <div
        class="fixed inset-0 z-[9999]"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        <div
          class="bg-[#1a1a1a] border border-[#3a3a3a] rounded px-2 py-0.5 text-[13px] text-[#e0e0e0] whitespace-nowrap pointer-events-none"
          style={`position:fixed;left:${ds().mouseX + 12}px;top:${ds().mouseY + 12}px`}
        >
          {ds().tabLabel}
        </div>
      </div>
    </Show>
  )
}

// --- list drag overlay ---

function calcListInsertIndex(listEl: Element, y: number): number {
  const items = listEl.querySelectorAll(
    "[data-drag-item]:not([data-drag-ghost])",
  )
  let insertIdx = 0
  items.forEach((item, idx) => {
    const rect = item.getBoundingClientRect()
    if (y > rect.top + rect.height / 2) {
      insertIdx = idx + 1
    }
  })
  return insertIdx
}

function hitTestList(x: number, y: number): { listId: string | null; insertIndex: number } {
  const lists = document.querySelectorAll("[data-list-id]")
  for (const el of lists) {
    const rect = el.getBoundingClientRect()
    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
      return {
        listId: el.getAttribute("data-list-id"),
        insertIndex: calcListInsertIndex(el, y),
      }
    }
  }
  return { listId: null, insertIndex: -1 }
}

export function ListDragOverlay(props: { onDrop: (listId: string, insertIndex: number) => void }) {
  const ds = () => listDragState()

  const handleMouseMove = (e: MouseEvent) => {
    updateListDragPosition(e.clientX, e.clientY)
    const { listId, insertIndex } = hitTestList(e.clientX, e.clientY)
    if (listId === ds().listId) {
      setListDragInsert(insertIndex)
    }
  }

  const handleMouseUp = (e: MouseEvent) => {
    updateListDragPosition(e.clientX, e.clientY)
    const { listId, insertIndex } = hitTestList(e.clientX, e.clientY)
    if (listId === ds().listId) {
      setListDragInsert(insertIndex)
      props.onDrop(ds().listId, insertIndex >= 0 ? insertIndex : 0)
    } else {
      endListDrag()
    }
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      endListDrag()
    }
  }

  createEffect(() => {
    if (ds().isDragging) {
      document.body.classList.add("drag-grabbing")
      document.addEventListener("keydown", handleKeyDown)
      onCleanup(() => {
        document.body.classList.remove("drag-grabbing")
        document.removeEventListener("keydown", handleKeyDown)
      })
    }
  })

  return (
    <Show when={ds().isDragging}>
      <div
        class="fixed inset-0 z-[9999]"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        <div
          class="bg-[#1a1a1a] border border-[#3a3a3a] rounded px-2 py-0.5 text-[13px] text-[#e0e0e0] whitespace-nowrap pointer-events-none"
          style={`position:fixed;left:${ds().mouseX + 12}px;top:${ds().mouseY + 12}px`}
        >
          {ds().itemLabel}
        </div>
      </div>
    </Show>
  )
}
