/** Shared state for the App keyboard handler, split into domain modules.
 *  Each domain module exports `handleX(e, state): boolean` (true = handled,
 *  caller stops). App.tsx wires them in dispatch order with the form-element
 *  gate between global and bare-key handlers.
 *
 *  `spaceHeld` and `moveMode` live here (component-local, no reactivity needed
 *  outside event handlers). `_selectedEl` is a plain DOM ref exposed via a
 *  getter; `setSelection` toggles the `keyboard-selected` class. `shiftHeld`
 *  stays global (in viewport-tree-store) because Viewport.tsx reads it for
 *  highlight rendering. */

import { createSignal } from "solid-js"
import { setShiftHeld } from "../../stores/viewport-tree-store"
import { setMoveHint } from "../../drag/drag-state"
import { linkingMode, cancelLinking } from "../../stores/settings-store"

export interface MoveMode {
  itemId: string
  listId: "sessions" | "notebook"
  originalIndex: number
  offset: number
  listLength: number
}

export interface KeyboardState {
  spaceHeld: () => boolean
  setSpaceHeld: (v: boolean) => void
  moveMode: () => MoveMode | null
  setMoveMode: (v: MoveMode | null) => void
  selectedEl: () => HTMLElement | null
  setSelection: (el: HTMLElement | null) => void
}

export function createKeyboardState(): KeyboardState {
  const [spaceHeld, setSpaceHeld] = createSignal(false)
  const [moveMode, setMoveMode] = createSignal<MoveMode | null>(null)
  let _selectedEl: HTMLElement | null = null

  function setSelection(el: HTMLElement | null) {
    if (_selectedEl) _selectedEl.classList.remove("keyboard-selected")
    _selectedEl = el
    if (el) el.classList.add("keyboard-selected")
  }

  return {
    spaceHeld,
    setSpaceHeld,
    moveMode,
    setMoveMode,
    selectedEl: () => _selectedEl,
    setSelection,
  }
}

/** Space/Shift keydown tracking — always dispatched first. Returns true when
 *  it consumed the event (Space or Shift pressed outside a form field). */
export function trackModifierDown(e: KeyboardEvent, state: KeyboardState): boolean {
  if (e.key === " " && !e.repeat) {
    const tag = (e.target as HTMLElement).tagName
    if (tag !== "INPUT" && tag !== "TEXTAREA") {
      e.preventDefault()
      state.setSpaceHeld(true)
      return true
    }
  }
  if (e.key === "Shift" && !e.repeat) {
    const tag = (e.target as HTMLElement).tagName
    if (tag !== "INPUT" && tag !== "TEXTAREA") {
      setShiftHeld(true)
      return true
    }
  }
  return false
}

/** Space/Shift keyup — resets the held flags and tears down Space-bound modes
 *  (selection, move-mode, linking). Mirrors the original onKeyUp. */
export function trackModifierUp(e: KeyboardEvent, state: KeyboardState): void {
  if (e.key === " ") {
    state.setSpaceHeld(false)
    state.setSelection(null)
    state.setMoveMode(null)
    setMoveHint(null)
    if (linkingMode()) cancelLinking()
  }
  if (e.key === "Shift") {
    setShiftHeld(false)
  }
}
