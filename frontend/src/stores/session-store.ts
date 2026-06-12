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

export async function createNewSession(): Promise<Session> {
  const res = await fetch("/api/sessions", { method: "POST" })
  const session: Session = await res.json()
  setSessions((prev) => [...prev, session])
  setActiveSessionId(session.id)
  broadcastSessionChange()
  return session
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
