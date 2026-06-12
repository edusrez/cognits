import { createStore, produce, reconcile, unwrap } from "solid-js/store"
import { createSignal } from "solid-js"

export type ViewportId = string

export interface Tab {
  id: string
  label: string
  hidden: boolean
}

export interface ViewportData {
  tabs: Tab[]
  activeTabId: string | null
}

export interface SplitData {
  parentId: ViewportId | null
  direction: "h" | "v"
  children: [ViewportId, ViewportId]
  fractions: [number, number]
}

export interface DesktopState {
  viewports: Record<ViewportId, ViewportData>
  splits: Record<ViewportId, SplitData>
  rootId: ViewportId
}

const [viewportMap, setViewportMap] = createStore<Record<ViewportId, ViewportData>>({})
const [splitMap, setSplitMap] = createStore<Record<ViewportId, SplitData>>({})

const [rootIdSignal, setRootId] = createSignal<ViewportId>("1")

export function rootId(): ViewportId {
  return rootIdSignal()
}

export function getViewportData(id: ViewportId): ViewportData | undefined {
  return viewportMap[id]
}

export function getSplitData(id: ViewportId): SplitData | undefined {
  return splitMap[id]
}

export function createDefaultTree(n: string) {
  const l = n + "0"
  const r = n + "1"
  const rl = r + "0"
  const rr = r + "1"
  const rll = rl + "0"
  const rlr = rl + "1"

  setRootId(n)

  setViewportMap(reconcile({
    [l]: {
      tabs: [
        { id: "files", label: "Archivos", hidden: false },
        { id: "sessions", label: "Sesiones", hidden: false },
      ],
      activeTabId: "files",
    },
    [rll]: { tabs: [], activeTabId: null },
    [rlr]: { tabs: [], activeTabId: null },
    [rr]: {
      tabs: [
        { id: "settings", label: "Ajustes", hidden: false },
        { id: "learnit", label: ".learnit", hidden: false },
      ],
      activeTabId: "settings",
    },
  }))

  setSplitMap(reconcile({
    [n]: {
      parentId: null,
      direction: "h",
      children: [l, r],
      fractions: [1, 5],
    },
    [r]: {
      parentId: n,
      direction: "h",
      children: [rl, rr],
      fractions: [4, 1],
    },
    [rl]: {
      parentId: r,
      direction: "v",
      children: [rll, rlr],
      fractions: [3, 1],
    },
  }))
}

export function createSettingsOnlyTree(n: string) {
  setRootId(n)
  setViewportMap(reconcile({
    [n]: {
      tabs: [{ id: "settings", label: "Ajustes", hidden: false }],
      activeTabId: "settings",
    },
  }))
  setSplitMap(reconcile({}))
}

export function snapshotTree(): DesktopState {
  // structuredClone es nativo y mucho más barato que el round-trip por JSON;
  // unwrap saca el objeto plano de debajo del proxy del store.
  return structuredClone({
    viewports: unwrap(viewportMap),
    splits: unwrap(splitMap),
    rootId: rootIdSignal(),
  })
}

export function loadTreeState(state: DesktopState) {
  setViewportMap(reconcile(state.viewports))
  setSplitMap(reconcile(state.splits))
  setRootId(state.rootId)
}

export type CtxMenu =
  | { kind: "viewport"; vpId: ViewportId; x: number; y: number }
  | { kind: "text-input"; vpId: ViewportId; x: number; y: number }
  | { kind: "session"; sessionId: string; x: number; y: number }
  | { kind: "report"; reportId: string; reportTitle: string; x: number; y: number }
  | { kind: "tab"; vpId: ViewportId; tabId: string; tabLabel: string; x: number; y: number }
  | { kind: "chat-message"; content: string; x: number; y: number }
  | { kind: "report-content"; content: string; reportId: string; title: string; x: number; y: number }
  | null

export const [ctxMenu, setCtxMenu] = createSignal<CtxMenu>(null)

export function resetTree() {
  const n = rootIdSignal()
  createDefaultTree(n)
  removeSessionTabs()
}
export function setFraction(splitId: ViewportId, index: 0 | 1, value: number) {
  setSplitMap(splitId, "fractions", index, Math.max(0.5, value))
}

export function activateTab(vpId: ViewportId, tabId: string) {
  setViewportMap(vpId, "activeTabId", tabId)
}

export function setTabLabel(vpId: ViewportId, tabId: string, label: string) {
  setViewportMap(
    produce((m) => {
      const vp = m[vpId]
      if (!vp) return
      const tab = vp.tabs.find((t) => t.id === tabId)
      if (tab) tab.label = label
    }),
  )
}

export function moveTab(
  tabId: string,
  fromVp: ViewportId,
  toVp: ViewportId,
  insertIndex: number,
) {
  setViewportMap(
    produce((m) => {
      const from = m[fromVp]
      if (!from) return
      const to = m[toVp]
      if (!to) return
      const idx = from.tabs.findIndex((t) => t.id === tabId)
      if (idx === -1) return
      const [tab] = from.tabs.splice(idx, 1)
      if (from.activeTabId === tabId) {
        from.activeTabId = from.tabs[0]?.id ?? null
      }
      const clamped = Math.min(insertIndex, to.tabs.length)
      to.tabs.splice(clamped, 0, tab)
      to.activeTabId = tab.id
    }),
  )
}

const sessionTabIds = ["chat", "write"]

export function placeSessionTabs(chatVp: ViewportId, writeVp: ViewportId) {
  setViewportMap(
    produce((m) => {
      for (const vp of Object.values(m)) {
        vp.tabs = vp.tabs.filter((t) => !sessionTabIds.includes(t.id))
        if (
          vp.activeTabId &&
          sessionTabIds.includes(vp.activeTabId)
        ) {
          vp.activeTabId = vp.tabs[0]?.id ?? null
        }
      }
      if (m[chatVp]) {
        m[chatVp].tabs.push({ id: "chat", label: "Chat", hidden: false })
        m[chatVp].activeTabId = "chat"
      }
      if (m[writeVp]) {
        m[writeVp].tabs.push({ id: "write", label: "Escribir", hidden: false })
        m[writeVp].activeTabId = "write"
      }
    }),
  )
}

export function removeSessionTabs() {
  setViewportMap(
    produce((m) => {
      for (const vp of Object.values(m)) {
        vp.tabs = vp.tabs.filter((t) => !sessionTabIds.includes(t.id))
        if (
          vp.activeTabId &&
          sessionTabIds.includes(vp.activeTabId)
        ) {
          vp.activeTabId = vp.tabs[0]?.id ?? null
        }
      }
    }),
  )
}

export function splitViewport(vpId: ViewportId, direction: "h" | "v") {
  const leftId = vpId + "0"
  const rightId = vpId + "1"
  const existing = viewportMap[vpId]
  if (!existing) return

  // El split nuevo hereda el id del viewport dividido, así que la referencia
  // en el padre (si lo hay) sigue siendo válida sin tocarla.
  setViewportMap(leftId, { tabs: [...existing.tabs], activeTabId: existing.activeTabId })
  setViewportMap(rightId, { tabs: [], activeTabId: null })
  setSplitMap(vpId, {
    parentId: findParentSplit(vpId),
    direction,
    children: [leftId, rightId],
    fractions: [1, 1],
  })
  setViewportMap(
    produce((m) => {
      delete m[vpId]
    }),
  )
}

export function countViewports(): number {
  return Object.keys(viewportMap).length
}

export function canDeleteViewport(id: ViewportId): boolean {
  if (countViewports() <= 1) return false
  const vp = viewportMap[id]
  if (vp && vp.tabs.some((t) => t.id === "settings")) return false
  return true
}

export function deleteViewport(vpId: ViewportId) {
  if (!canDeleteViewport(vpId)) return

  const parentId = findParentSplit(vpId)
  if (!parentId) return

  const parent = splitMap[parentId]
  if (!parent) return

  const dying = viewportMap[vpId]
  if (dying && dying.tabs.some((t) => t.id === "settings")) return

  const siblingIdx = parent.children[0] === vpId ? 1 : 0
  const siblingId = parent.children[siblingIdx]
  const grandparentId = parent.parentId

  if (dying && dying.tabs.length > 0) {
    absorbTabs(siblingId, dying.tabs, dying.activeTabId)
  }

  setViewportMap(
    produce((m) => {
      delete m[vpId]
    }),
  )

  setSplitMap(
    produce((s) => {
      delete s[parentId]

      if (grandparentId) {
        const gp = s[grandparentId]
        if (gp) {
          const idx = gp.children.indexOf(parentId) as 0 | 1
          if (idx >= 0) gp.children[idx] = siblingId
        }
        if (s[siblingId]) s[siblingId].parentId = grandparentId
      } else {
        setRootId(siblingId)
        if (s[siblingId]) s[siblingId].parentId = null
      }
    }),
  )
}

function absorbTabs(
  targetId: ViewportId,
  tabs: Tab[],
  activeTabId: string | null,
) {
  const firstLeaf = findFirstLeaf(targetId)
  if (!firstLeaf) return
  setViewportMap(
    produce((m) => {
      m[firstLeaf].tabs.push(...tabs)
      if (!m[firstLeaf].activeTabId && activeTabId) {
        m[firstLeaf].activeTabId = activeTabId
      }
    }),
  )
}

function findFirstLeaf(id: ViewportId): ViewportId | null {
  if (viewportMap[id]) return id
  const split = splitMap[id]
  if (!split) return null
  return findFirstLeaf(split.children[0])
}

function findParentSplit(childId: ViewportId): ViewportId | null {
  for (const [sid, split] of Object.entries(splitMap)) {
    if (split.children.includes(childId)) return sid
  }
  return null
}

export function addDynamicTab(vpId: ViewportId, tab: { id: string; label: string; hidden: boolean }) {
  setViewportMap(
    produce((m) => {
      const vp = m[vpId]
      if (!vp) return
      if (!vp.tabs.some((t) => t.id === tab.id)) {
        vp.tabs.push({ ...tab, label: tab.label })
      }
      vp.activeTabId = tab.id
    }),
  )
}

export function removeDynamicTab(vpId: ViewportId, tabId: string) {
  setViewportMap(
    produce((m) => {
      const vp = m[vpId]
      if (!vp) return
      vp.tabs = vp.tabs.filter((t) => t.id !== tabId)
      if (vp.activeTabId === tabId) {
        vp.activeTabId = vp.tabs[0]?.id ?? null
      }
    }),
  )
}
