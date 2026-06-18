/** Selection & list-item actions — operate on the keyboard-selected element
 *  (the `keyboard-selected` class managed by state.setSelection).
 *  - cancelMoveModeOnKey: side-effect that resets move mode on any non-arrow/m
 *    key. Called before the dispatch chain (non-returning).
 *  - handleSpaceEnter: Space+Enter activates the selected session/note/element.
 *  - handleSpaceShortcuts: Space+d (delete), c (close tab), m (move toggle/
 *    commit), r (rename). No modifier guard — fires whenever space is held.
 *  - handleCtrlEnter: Ctrl+Enter blurs the focused form field and clears the
 *    selection. */

import { activeSessionId, setActiveSessionId, deleteSession, setRenamingSessionId } from "../../stores/session-store"
import { defaultLearnitViewport } from "../../stores/settings-store"
import { focusedViewportId } from "../../stores/viewport-tree-store"
import { getViewportData, removeDynamicTab } from "../../stores/viewport-tree-store"
import { isDynamicTab } from "../../tabs"
import { setMoveHint } from "../../drag/drag-state"
import type { KeyboardState } from "./state"

/** Reset move mode on any key except arrows/m (non-returning side effect). */
export function cancelMoveModeOnKey(e: KeyboardEvent, state: KeyboardState): void {
  if (state.moveMode() && !e.repeat && e.key !== "ArrowUp" && e.key !== "ArrowDown" && e.key !== "m") {
    state.setMoveMode(null)
    setMoveHint(null)
  }
}

/** Space+Enter: activate the keyboard-selected element (toggle session, open
 *  note, focus input, or click). Guards: no ctrl/shift/alt, space held, a
 *  selected element exists, target not a form field. */
export function handleSpaceEnter(e: KeyboardEvent, state: KeyboardState): boolean {
  if (!(e.ctrlKey === false && !e.shiftKey && !e.altKey)) return false
  if (!(e.key === "Enter" && state.spaceHeld() && state.selectedEl() && !e.repeat)) return false
  const tag = (e.target as HTMLElement).tagName
  if (tag === "INPUT" || tag === "TEXTAREA") return false
  e.preventDefault()
  const el = state.selectedEl()!
  state.setSelection(null)
  if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
    el.focus?.({ focusVisible: true } as FocusOptions)
    return true
  }
  const sid = el.getAttribute("data-session-id")
  const nid = el.getAttribute("data-note-id")
  if (sid) {
    setActiveSessionId(activeSessionId() === sid ? null : sid)
  } else if (nid) {
    import("../../stores/notebook-store").then((m) =>
      m.openNoteInViewport(defaultLearnitViewport(), nid),
    )
  } else {
    el.click?.()
  }
  return true
}

/** Space-held shortcuts: d (delete selected), c (close active dynamic tab),
 *  m (toggle/commit move mode), r (rename session). No modifier guard. */
export function handleSpaceShortcuts(e: KeyboardEvent, state: KeyboardState): boolean {
  if (!(state.spaceHeld() && !e.repeat)) return false
  if (e.key === "d" && state.selectedEl()) {
    const el = state.selectedEl()!
    const sid = el.getAttribute("data-session-id")
    if (sid) { e.preventDefault(); state.setSelection(null); deleteSession(sid); return true }
    const rid = el.getAttribute("data-report-id")
    if (rid) {
      e.preventDefault(); state.setSelection(null)
      fetch(`/api/reports/${rid}`, { method: "DELETE" })
        .then(() => import("../../stores/learnit-store").then((m) => m.refetchReports()))
      return true
    }
    const nid = el.getAttribute("data-note-id")
    if (nid) {
      e.preventDefault(); state.setSelection(null)
      import("../../stores/notebook-store").then((m) => m.deleteNote(nid))
      return true
    }
    return true
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
    return true
  }
  if (e.key === "m") {
    handleMoveKey(state)
    return true
  }
  if (e.key === "r" && state.selectedEl()) {
    const sid = state.selectedEl()!.getAttribute("data-session-id")
    if (sid) {
      e.preventDefault()
      state.setSelection(null)
      setRenamingSessionId(sid)
    }
    return true
  }
  return false
}

/** Move-key (m): if a move is in progress, commit it; otherwise start move
 *  mode for the selected list item (session or note). */
function handleMoveKey(state: KeyboardState): void {
  const mm = state.moveMode()
  if (mm) {
    const targetIndex = mm.originalIndex + mm.offset
    state.setMoveMode(null)
    setMoveHint(null)
    if (mm.listId === "sessions") {
      import("../../stores/session-store").then((m) => m.moveSession(mm.itemId, targetIndex))
    } else {
      import("../../stores/notebook-store").then((m) => m.moveNote(mm.itemId, targetIndex))
    }
    return
  }
  const sel = state.selectedEl()
  if (!sel) return
  const sid = sel.getAttribute("data-session-id")
  const nid = sel.getAttribute("data-note-id")
  const id = sid || nid
  if (!id) return
  const listId: "sessions" | "notebook" = sid ? "sessions" : "notebook"
  const listEl = sel.closest("[data-list-id]")
  const items = listEl?.querySelectorAll("[data-drag-item]")
  const allIds = Array.from(items ?? []).map(
    (el) => el.getAttribute(sid ? "data-session-id" : "data-note-id") ?? "",
  )
  const idx = allIds.indexOf(id)
  if (idx >= 0) {
    state.setMoveMode({ itemId: id, listId, originalIndex: idx, offset: 0, listLength: allIds.length })
    setMoveHint({ listId, itemId: id, targetIndex: idx })
  }
}

/** Ctrl+Enter: blur the focused form field and clear keyboard selection. */
export function handleCtrlEnter(e: KeyboardEvent, state: KeyboardState): boolean {
  if (!(e.ctrlKey && !e.shiftKey && !e.altKey && e.key === "Enter")) return false
  const tag = (e.target as HTMLElement).tagName
  if (tag !== "INPUT" && tag !== "TEXTAREA") return false
  e.preventDefault()
  const el = e.target as HTMLElement
  el.blur()
  state.setSelection(null)
  return true
}
