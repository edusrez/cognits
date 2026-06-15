import { createSignal } from "solid-js"

export interface Session {
  id: string
  name: string
  createdAt: string
}

export const [activeSessionId, setActiveSessionId] = createSignal<string | null>(
  null,
)

export const [sessions, setSessions] = createSignal<Session[]>([])

let sessionChannel: BroadcastChannel | null = null

try {
  sessionChannel = new BroadcastChannel("desktop-sync")
  sessionChannel.onmessage = (e: MessageEvent) => {
    if (e.data?.type === "SESSIONS_CHANGED") {
      loadSessions()
    }
  }
} catch {
  sessionChannel = null
}

function broadcastSessionChange() {
  if (sessionChannel) {
    sessionChannel.postMessage({ type: "SESSIONS_CHANGED" })
  }
}

export async function loadSessions() {
  const res = await fetch("/api/sessions")
  if (res.ok) {
    setSessions(await res.json())
  }
}

export const [isCreatingSession, setIsCreatingSession] = createSignal(false)

export const [renamingSessionId, setRenamingSessionId] = createSignal<string | null>(null)

export async function createNewSession(): Promise<Session> {
  if (isCreatingSession()) throw new Error("Already creating")
  setIsCreatingSession(true)
  try {
    const res = await fetch("/api/sessions", { method: "POST" })
    const session: Session = await res.json()
    setSessions((prev) => {
      if (prev.some((s) => s.id === session.id)) return prev
      return [...prev, session]
    })
    setActiveSessionId(session.id)
    broadcastSessionChange()
    return session
  } finally {
    setIsCreatingSession(false)
  }
}

export async function renameSession(id: string, name: string) {
  await fetch(`/api/sessions/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })
  setSessions((prev) =>
    prev.map((s) => (s.id === id ? { ...s, name } : s)),
  )
  broadcastSessionChange()
}

export async function deleteSession(id: string) {
  await fetch(`/api/sessions/${id}`, { method: "DELETE" })
  setSessions((prev) => prev.filter((s) => s.id !== id))
  if (activeSessionId() === id) {
    setActiveSessionId(null)
  }
  broadcastSessionChange()
}

export async function moveSession(itemId: string, insertIndex: number) {
  setSessions((prev) => {
    const fromIdx = prev.findIndex((s) => s.id === itemId)
    if (fromIdx < 0) return prev
    const item = prev[fromIdx]
    const rest = [...prev.slice(0, fromIdx), ...prev.slice(fromIdx + 1)]
    const clamped = Math.min(insertIndex, rest.length)
    return [...rest.slice(0, clamped), item, ...rest.slice(clamped)]
  })

  const order = sessions().map((s) => s.id)
  await fetch("/api/sessions/reorder", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order }),
  })
  broadcastSessionChange()
}
