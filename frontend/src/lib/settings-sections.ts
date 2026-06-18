/** Declarative registry of Settings sections.
 * Add a section here once — Settings.tsx and the context menu auto-discover it. */
import type { JSXElement } from "solid-js"
import { baseTabId } from "./tab-kinds"

export interface SectionContext {
  linkedViewport: boolean
  tabId: string | null
  /** True when this Settings instance is a scoped tab (e.g. "settings:files")
   *  opened via the context menu, as opposed to the base linked Settings.
   *  Constant per instance (derived from props.tabId), so a plain value is
   *  fine — no reactivity needed. */
  scoped: boolean
  /** Per-instance reactive fields. Accessors (not plain values) because
   *  render() is invoked once per section by the <For> in the shell — a plain
   *  value would be captured stale. The shell passes its createMemo directly. */
  pdfPath?: () => string | null
}

export interface SettingSection {
  id: string
  /** Returns true when this section should be visible in the Settings panel. */
  matches(ctx: SectionContext): boolean
  /** Returns the JSX for this section. Receives the same context used for
   *  matching, plus any per-instance fields the shell injects (e.g. pdfPath).
   *  Sections that don't need ctx may declare `render()` — TS contravariance
   *  accepts fewer-param functions. */
  render(ctx: SectionContext): JSXElement
}

/** All setting sections in priority order. */
const registry: SettingSection[] = []

export function registerSection(section: SettingSection) {
  registry.push(section)
}

export function getAllSections(): ReadonlyArray<SettingSection> {
  return registry
}

export function getMatchingSections(ctx: SectionContext): SettingSection[] {
  const matched = registry.filter((s) => s.matches(ctx))
  // \"general\" is the catch-all footer (basic tabs, restore layout, change
  // link). Keep it last regardless of registration order, so per-tab sections
  // appear above it.
  const general = matched.find((s) => s.id === "general")
  if (!general) return matched
  return [...matched.filter((s) => s.id !== "general"), general]
}

/** True if any section matches this tab (used by Viewport context menu). */
export function hasSettings(tabId: string): boolean {
  return registry.some((s) => s.matches({ linkedViewport: true, tabId, scoped: false }))
}

/** Strip dynamic suffixes from tab IDs for the settings scope.
 *  "report:abc123"  → "report"
 *  "code:/path/py"  → "code"
 *  "pdf:/path/p.pdf" → "pdf"
 *  "files"          → "files"
 */
export function getSettingsScope(tabId: string): string {
  return baseTabId(tabId)
}
