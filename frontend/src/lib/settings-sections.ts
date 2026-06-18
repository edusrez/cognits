/** Declarative registry of Settings sections.
 * Add a section here once — Settings.tsx and the context menu auto-discover it. */
import type { JSXElement } from "solid-js"
import { baseTabId } from "./tab-kinds"

export interface SectionContext {
  linkedViewport: boolean
  tabId: string | null
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
  return registry.filter((s) => s.matches(ctx))
}

/** True if any section matches this tab (used by Viewport context menu). */
export function hasSettings(tabId: string): boolean {
  return registry.some((s) => s.matches({ linkedViewport: true, tabId }))
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
