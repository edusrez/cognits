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
export const [focusedViewportId, setFocusedViewportId] = createSignal<string | null>(null)
export const [shiftHeld, setShiftHeld] = createSignal(false)

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
        { id: "files", label: "Files", hidden: false },
        { id: "sessions", label: "Sessions", hidden: false },
      ],
      activeTabId: "files",
    },
    [rll]: { tabs: [], activeTabId: null },
    [rlr]: { tabs: [], activeTabId: null },
    [rr]: {
      tabs: [
        { id: "settings", label: "Settings", hidden: false },
        { id: "learnit", label: ".cognits", hidden: false },
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
      tabs: [{ id: "settings", label: "Settings", hidden: false }],
      activeTabId: "settings",
    },
  }))
  setSplitMap(reconcile({}))
}

export function snapshotTree(): DesktopState {
  // structuredClone is native and much cheaper than the JSON round-trip;
  // unwrap extracts the plain object from beneath the store proxy.
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
        m[chatVp].tabs.push({ id: "chat", label: "Chat", hidden: true })
        m[chatVp].activeTabId = "chat"
      }
      if (m[writeVp]) {
        m[writeVp].tabs.push({ id: "write", label: "Write", hidden: true })
        m[writeVp].activeTabId = "write"
      }
    }),
  )
}

export function removeSessionTabs() {
  setViewportMap(
    produce((m) => {
      for (const vp of Object.values(m)) {
        vp.tabs = vp.tabs.filter(
          (t) => !sessionTabIds.includes(t.id) && !t.id.startsWith("report:")
        )
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

  // The new split inherits the split viewport's id, so the reference
  // in the parent (if any) remains valid without touching it.
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

export function getViewportIds(): ViewportId[] {
  return Object.keys(viewportMap).sort()
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

export function swapAdjacentTabs(vpId: ViewportId, tabId: string, right: boolean) {
  setViewportMap(
    produce((m) => {
      const vp = m[vpId]
      if (!vp) return
      const idx = vp.tabs.findIndex((t) => t.id === tabId)
      if (idx < 0) return
      const target = right ? idx + 1 : idx - 1
      if (target < 0 || target >= vp.tabs.length) return
      const tmp = vp.tabs[idx]
      vp.tabs[idx] = vp.tabs[target]
      vp.tabs[target] = tmp
      vp.activeTabId = tabId
    }),
  )
}

export function computeViewportPositions(): Record<string, { x: number; y: number; w: number; h: number }> {
  const positions: Record<string, { x: number; y: number; w: number; h: number }> = {}

  function walk(id: string, x: number, y: number, w: number, h: number) {
    const split = splitMap[id]
    if (!split) {
      positions[id] = { x, y, w, h }
      return
    }
    const [f0, f1] = split.fractions
    const t = f0 + f1
    if (split.direction === "h") {
      walk(split.children[0], x, y, (w * f0) / t, h)
      walk(split.children[1], x + (w * f0) / t, y, (w * f1) / t, h)
    } else {
      walk(split.children[0], x, y, w, (h * f0) / t)
      walk(split.children[1], x, y + (h * f0) / t, w, (h * f1) / t)
    }
  }

  walk(rootIdSignal(), 0, 0, 1, 1)
  return positions
}

export function findSpatialNeighbor(
  currentId: string,
  direction: "left" | "right" | "up" | "down",
  rects: Record<string, { x: number; y: number; w: number; h: number }>,
): string | null {
  const cur = rects[currentId]
  if (!cur) return null

  let best: { id: string; dist: number; overlap: number } | null = null

  for (const [id, r] of Object.entries(rects)) {
    if (id === currentId) continue

    let dist = 0
    let overlap = 0
    let candidate = false

    if (direction === "right") {
      // must be to the right AND vertically overlap
      if (r.x >= cur.x + cur.w && r.y < cur.y + cur.h && r.y + r.h > cur.y) {
        dist = r.x - (cur.x + cur.w)
        overlap = Math.min(r.y + r.h, cur.y + cur.h) - Math.max(r.y, cur.y)
        candidate = true
      }
    } else if (direction === "left") {
      if (r.x + r.w <= cur.x && r.y < cur.y + cur.h && r.y + r.h > cur.y) {
        dist = cur.x - (r.x + r.w)
        overlap = Math.min(r.y + r.h, cur.y + cur.h) - Math.max(r.y, cur.y)
        candidate = true
      }
    } else if (direction === "down") {
      // must be below AND horizontally overlap
      if (r.y >= cur.y + cur.h && r.x < cur.x + cur.w && r.x + r.w > cur.x) {
        dist = r.y - (cur.y + cur.h)
        overlap = Math.min(r.x + r.w, cur.x + cur.w) - Math.max(r.x, cur.x)
        candidate = true
      }
    } else if (direction === "up") {
      if (r.y + r.h <= cur.y && r.x < cur.x + cur.w && r.x + r.w > cur.x) {
        dist = cur.y - (r.y + r.h)
        overlap = Math.min(r.x + r.w, cur.x + cur.w) - Math.max(r.x, cur.x)
        candidate = true
      }
    }

    if (candidate && (!best || dist < best.dist || (dist === best.dist && overlap > best.overlap))) {
      best = { id, dist, overlap }
    }
  }

  return best?.id ?? null
}
