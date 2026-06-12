import { createEffect, onCleanup, Show } from "solid-js"
import {
  dragState,
  updateDragPosition,
  setDragTarget,
  endDrag,
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
