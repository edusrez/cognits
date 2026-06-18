/** Desktop management bare-key shortcuts (fire after the form-element gate).
 *  - n: create a new desktop.
 *  - digits 1-9: switch to desktop N (capped by desktopCount). */

import { createDesktop, switchDesktop, desktopCount } from "../../stores/desktop-store"

export function handleDesktopShortcuts(e: KeyboardEvent): boolean {
  if (!(e.ctrlKey === false && !e.shiftKey && !e.altKey)) return false
  if (e.key === "n") {
    e.preventDefault()
    createDesktop()
    return true
  }
  const num = parseInt(e.key)
  if (num >= 1 && num <= 9 && num <= desktopCount()) {
    e.preventDefault()
    switchDesktop(num - 1)
    return true
  }
  return false
}
