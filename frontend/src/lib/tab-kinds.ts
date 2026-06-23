/** Tab identity helpers — single source of truth for the dynamic-tab prefix
 *  conventions used across App, Viewport, TabBar, Settings, and the section
 *  registry. Pure module (no component imports) so it can be imported from
 *  anywhere — including the section registry — without creating cycles.
 *
 *  Dynamic tabs carry a payload after ":" — e.g. "pdf:/foo.pdf",
 *  "settings:files", "report:abc123". Static tabs are bare ids ("files",
 *  "chat", ...). */

/** Canonical human labels for every tab kind. The tabs registry in tabs.ts
 *  derives its labels from this map so there is exactly one source of truth. */
export const TAB_LABELS: Record<string, string> = {
  setup: "Setup",
  files: "Files",
  sessions: "Sessions",
  chat: "Chat",
  write: "Write",
  settings: "Settings",
  report: "Web Report",
  note: "Note",
  learnit: ".cognits",
  code: "Code",
  text: "Text",
  image: "Image",
  pdf: "PDF",
}

/** Kinds that may appear as dynamic tabs carrying a ":" payload. */
export const DYNAMIC_TAB_KINDS = [
  "report", "settings", "note", "code", "text", "image", "pdf",
] as const

/** True for tabs with a payload suffix, e.g. "pdf:/foo.pdf", "settings:files". */
export function isDynamicTab(id: string): boolean {
  return id.includes(":")
}

/** Base kind of a tab id: "pdf:/x" → "pdf", "files" → "files". */
export function baseTabId(id: string): string {
  const i = id.indexOf(":")
  return i >= 0 ? id.slice(0, i) : id
}

/** Payload portion of a dynamic tab, or null for static tabs. */
export function dynamicPayload(id: string): string | null {
  const i = id.indexOf(":")
  return i >= 0 ? id.slice(i + 1) : null
}

/** Canonical kind for matching: returns baseTabId if it is a known tab kind,
 *  else null. Use this instead of startsWith(":") chains. */
export function tabKind(id: string | null | undefined): string | null {
  if (!id) return null
  const base = baseTabId(id)
  return TAB_LABELS[base] !== undefined ? base : null
}

/** Human label for any tab id, derived from TAB_LABELS.
 *  "pdf:/x" → "PDF", "files" → "Files", unknown → null. */
export function tabDisplayName(id: string | null | undefined): string | null {
  if (!id) return null
  return TAB_LABELS[baseTabId(id)] ?? null
}
