/** Viewport & tab navigation handlers.
 *  - handleViewportFocus: Shift+Arrows (move focus between viewports), Shift+N
 *    (close active desktop). Fires before the form-element gate.
 *  - handleLinkMode: Space+Arrows/Enter while linkingMode is active. Fires
 *    before the form-element gate (global).
 *  - handleArrowNavigation: bare ArrowUp/Down/Left/Right — move-mode hint nav,
 *    Space+Arrows for focusable-item focus and tab swap, plain arrows for
 *    viewport scroll and tab switching. Fires AFTER the form-element gate. */

import {
  focusedViewportId,
  setFocusedViewportId,
  getViewportData,
  computeViewportPositions,
  findSpatialNeighbor,
  swapAdjacentTabs,
  activateTab,
} from "../../stores/viewport-tree-store"
import { activeSessionId } from "../../stores/session-store"
import { linkingMode, confirmLinkViewport } from "../../stores/settings-store"
import { closeDesktop, activeDesktopIndex } from "../../stores/desktop-store"
import { setMoveHint } from "../../drag/drag-state"
import type { KeyboardState } from "./state"

const ARROW_DIR = {
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  ArrowDown: "down",
} as const

/** Shift (no ctrl, no alt): move viewport focus spatially, or close desktop on N. */
export function handleViewportFocus(e: KeyboardEvent): boolean {
  if (!(e.shiftKey && !e.ctrlKey && !e.altKey)) return false
  if (e.key in ARROW_DIR) {
    const current = focusedViewportId()
    if (current) {
      const neighbor = findSpatialNeighbor(current, ARROW_DIR[e.key as keyof typeof ARROW_DIR], computeViewportPositions())
      if (neighbor) {
        e.preventDefault()
        setFocusedViewportId(neighbor)
      }
    }
    return true
  }
  if (e.key === "N") {
    e.preventDefault()
    closeDesktop(activeDesktopIndex())
    return true
  }
  return false
}

/** Link-viewport mode: Space+Arrows move the highlight, Enter confirms.
 *  Guards: no ctrl/shift/alt, linkingMode active, space held. */
export function handleLinkMode(e: KeyboardEvent, state: KeyboardState): boolean {
  if (!(e.ctrlKey === false && !e.shiftKey && !e.altKey && linkingMode() && state.spaceHeld())) return false
  if (e.key === "Enter") {
    const cur = focusedViewportId()
    if (cur) { e.preventDefault(); confirmLinkViewport(cur) }
    return true
  }
  if (e.key in ARROW_DIR) {
    const cur = focusedViewportId()
    if (cur) {
      const neighbor = findSpatialNeighbor(cur, ARROW_DIR[e.key as keyof typeof ARROW_DIR], computeViewportPositions())
      if (neighbor) { e.preventDefault(); setFocusedViewportId(neighbor) }
    }
    return true
  }
  return false
}

/** Bare-arrow navigation (post form-element gate). Order matches the original:
 *  1. ArrowUp/Down: move-mode hint nav → Space+focusable-item focus → scroll.
 *  2. ArrowLeft/Right: Space+swap adjacent tabs → tab switch. */
export function handleArrowNavigation(e: KeyboardEvent, state: KeyboardState): boolean {
  if (!(e.ctrlKey === false && !e.shiftKey && !e.altKey)) return false
  if (e.key === "ArrowUp" || e.key === "ArrowDown") {
    const mm = state.moveMode()
    if (mm) {
      e.preventDefault()
      const delta = e.key === "ArrowUp" ? -1 : 1
      const newOffset = mm.offset + delta
      const targetIdx = mm.originalIndex + newOffset
      if (targetIdx >= 0 && targetIdx < mm.listLength) {
        state.setMoveMode({ ...mm, offset: newOffset })
        setMoveHint({ listId: mm.listId, itemId: mm.itemId, targetIndex: targetIdx })
      }
      return true
    }
    const vpId = focusedViewportId()
    if (!vpId) return true
    if (state.spaceHeld()) {
      e.preventDefault()
      const vpEl = document.querySelector(`[data-viewport-id="${vpId}"]`)
      if (vpEl) {
        const items = getFocusableElements(vpEl as HTMLElement)
        if (items.length > 0) {
          const cur = state.selectedEl() || (document.activeElement as HTMLElement)
          let idx = items.indexOf(cur)
          if (idx < 0) idx = e.key === "ArrowDown" ? -1 : items.length
          const next = e.key === "ArrowDown"
            ? (idx + 1) % items.length
            : (idx - 1 + items.length) % items.length
          state.setSelection(items[next])
          items[next].scrollIntoView?.({ block: "nearest" })
        }
      }
      return true
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
    return true
  }
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    const vpId = focusedViewportId()
    if (!vpId) return true
    if (state.spaceHeld()) {
      const vp = getViewportData(vpId)
      if (vp && vp.activeTabId) {
        e.preventDefault()
        swapAdjacentTabs(vpId, vp.activeTabId, e.key === "ArrowRight")
      }
      return true
    }
    const vp = getViewportData(vpId)
    if (vp) {
      const vis = vp.tabs.filter((t) => !t.hidden || activeSessionId() !== null)
      if (vis.length === 0) return true
      const idx = vis.findIndex((t) => t.id === vp.activeTabId)
      const next = e.key === "ArrowRight"
        ? (idx + 1) % vis.length
        : (idx - 1 + vis.length) % vis.length
      e.preventDefault()
      activateTab(vpId, vis[next].id)
    }
    return true
  }
  return false
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
