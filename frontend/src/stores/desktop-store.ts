import { createSignal } from "solid-js"
import {
  snapshotTree,
  loadTreeState,
  createDefaultTree,
  createSettingsOnlyTree,
  placeSessionTabs,
  removeSessionTabs,
  setFraction,
  type DesktopState,
} from "./viewport-tree-store"
import { activeSessionId } from "./session-store"
import { defaultChatViewport, defaultWriteViewport } from "./settings-store"

// El efecto de App.tsx solo coloca las pestañas de sesión al cambiar de sesión;
// al restaurar otro árbol de escritorio hay que re-colocarlas explícitamente.
function restoreSessionTabs() {
  if (activeSessionId()) {
    placeSessionTabs(defaultChatViewport(), defaultWriteViewport())
  }
}

const [desktops, setDesktops] = createSignal<DesktopState[]>([])
const [activeIndex, setActiveIndex] = createSignal(0)

let desktopChannel: BroadcastChannel | null = null

function initChannel() {
  try {
    desktopChannel = new BroadcastChannel("desktop-sync")
    desktopChannel.onmessage = (e: MessageEvent) => {
      const data = e.data
      if (data?.type === "DESKTOPS_CHANGED" && data.desktops) {
        setDesktops(data.desktops)
      }
    }
  } catch {
    desktopChannel = null
  }
}

function persistDesktops() {
  // Los snapshots del signal ya son objetos planos (salen de snapshotTree);
  // no hace falta clonarlos antes de serializar.
  fetch("/api/desktops", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ desktops: desktops(), activeIndex: activeIndex() }),
  }).catch((err) => console.error("persist desktops:", err))
}

function syncDesktops() {
  persistDesktops()
  if (desktopChannel) {
    // postMessage ya hace structured clone del payload por su cuenta.
    desktopChannel.postMessage({
      type: "DESKTOPS_CHANGED",
      desktops: desktops(),
    })
  }
}

async function loadDesktops() {
  try {
    const res = await fetch("/api/desktops")
    if (!res.ok) return
    const data = await res.json()
    if (data.desktops?.length > 0) {
      setDesktops(data.desktops)
      setActiveIndex(data.activeIndex)
      loadTreeState(data.desktops[data.activeIndex])
      return true
    }
  } catch {}
  return false
}

export async function initDesktops() {
  initChannel()
  const loaded = await loadDesktops()
  if (!loaded) {
    createDefaultTree("1")
    setDesktops([snapshotTree()])
    persistDesktops()
  }
}

export function desktopCount(): number {
  return desktops().length
}

export function activeDesktopIndex(): number {
  return activeIndex()
}

function updateCurrentSnapshot() {
  setDesktops((prev) => {
    const next = [...prev]
    next[activeIndex()] = snapshotTree()
    return next
  })
}

export function createDesktop() {
  updateCurrentSnapshot()

  const max = desktops().reduce(
    (m, d) => Math.max(m, parseInt(d.rootId)),
    0,
  )
  const n = (max + 1).toString()

  createSettingsOnlyTree(n)
  removeSessionTabs()

  setDesktops((prev) => [...prev, snapshotTree()])
  setActiveIndex(desktops().length - 1)
  syncDesktops()
}

export function switchDesktop(index: number) {
  const ds = desktops()
  if (index < 0 || index >= ds.length) return
  if (index === activeIndex()) return

  updateCurrentSnapshot()
  loadTreeState(ds[index])
  restoreSessionTabs()
  setActiveIndex(index)
  persistDesktops()
}

export function closeDesktop(index: number) {
  const ds = desktops()
  if (ds.length <= 1) return

  updateCurrentSnapshot()

  const newDesktops = ds.filter((_, i) => i !== index)
  setDesktops(newDesktops)

  const newIndex = Math.min(activeIndex(), newDesktops.length - 1)
  loadTreeState(newDesktops[newIndex])
  restoreSessionTabs()
  setActiveIndex(newIndex)
  syncDesktops()
}
