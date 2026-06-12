import { createSignal, createMemo, batch } from "solid-js"
import { startChat, streamSession, type ChatMessage, type ChatUsage, type StreamCallbacks, type HistorySnapshot } from "../lib/chat-stream"
import { activeSessionId } from "./session-store"

export type { ChatMessage, ChatUsage }

const MAX_MESSAGES = 500

function capMessages(msgs: ChatMessage[]): ChatMessage[] {
  if (msgs.length <= MAX_MESSAGES) return msgs
  return msgs.slice(-MAX_MESSAGES)
}

async function loadFromDB(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(`/api/sessions/${sessionId}/messages`)
  if (!res.ok) return []
  const rows = await res.json()
  return rows.map((r: any) => ({
    role: r.role,
    content: r.content,
    reasoning: r.reasoning || undefined,
    reportId: r.reportId || undefined,
    reportTitle: r.reportTitle || undefined,
  }))
}

export const [messagesBySession, setMessagesBySession] = createSignal<
  Record<string, ChatMessage[]>
>({})

export const [usageBySession, setUsageBySession] = createSignal<
  Record<string, ChatUsage>
>({})

export const [toolStatusBySession, setToolStatusBySession] = createSignal<
  Record<string, string | null>
>({})

export const [errorBySession, setErrorBySession] = createSignal<
  Record<string, string | null>
>({})

type StreamState = { active: boolean; thinking: boolean }

export const [streamingBySession, setStreamingBySession] = createSignal<
  Record<string, StreamState>
>({})

function setStreamState(sid: string, state: Partial<StreamState>) {
  setStreamingBySession((prev) => ({
    ...prev,
    [sid]: { ...(prev[sid] ?? { active: false, thinking: false }), ...state },
  }))
}

export const currentMessages = createMemo(() => {
  const sid = activeSessionId()
  if (!sid) return []
  return messagesBySession()[sid] ?? []
})

export const sessionUsage = createMemo(() => {
  const sid = activeSessionId()
  if (!sid) return null
  return usageBySession()[sid] ?? null
})

export const currentToolStatus = createMemo(() => {
  const sid = activeSessionId()
  if (!sid) return null
  return toolStatusBySession()[sid] ?? null
})

export const currentChatError = createMemo(() => {
  const sid = activeSessionId()
  if (!sid) return null
  return errorBySession()[sid] ?? null
})

export const isStreaming = createMemo(() => {
  const sid = activeSessionId()
  if (!sid) return false
  return streamingBySession()[sid]?.active ?? false
})

export const isThinking = createMemo(() => {
  const sid = activeSessionId()
  if (!sid) return false
  return streamingBySession()[sid]?.thinking ?? false
})

let syncChannel: BroadcastChannel | null = null
try {
  syncChannel = new BroadcastChannel("desktop-sync")
  syncChannel.onmessage = (e: MessageEvent) => {
    const data = e.data
    if (data?.type === "AGENT_STARTED" && data.sessionId === activeSessionId()) {
      subscribeToSession(data.sessionId)
    }
  }
} catch {
  syncChannel = null
}

function broadcastAgentStarted(sessionId: string) {
  if (syncChannel) {
    syncChannel.postMessage({ type: "AGENT_STARTED", sessionId })
  }
}

// Un único stream activo en toda la app: suscribirse a una sesión aborta
// siempre el stream anterior (evita tokens duplicados con dos lectores).
let streamController: AbortController | null = null

// Los tokens del SSE se acumulan aquí y se aplican al store en lotes de ~50ms:
// actualizar el signal por cada token re-renderiza todo el chat decenas de
// veces por segundo. setTimeout y no rAF: en pestañas en segundo plano rAF se
// congela y el buffer crecería sin límite.
const pendingTokens = new Map<string, { content: string; reasoning: string }>()
let flushTimer: ReturnType<typeof setTimeout> | null = null

function pendingFor(sid: string) {
  let buf = pendingTokens.get(sid)
  if (!buf) {
    buf = { content: "", reasoning: "" }
    pendingTokens.set(sid, buf)
  }
  return buf
}

function scheduleFlush() {
  if (flushTimer !== null) return
  flushTimer = setTimeout(flushPendingTokens, 50)
}

function flushPendingTokens() {
  if (flushTimer !== null) {
    clearTimeout(flushTimer)
    flushTimer = null
  }
  if (pendingTokens.size === 0) return
  batch(() => {
    setMessagesBySession((prev) => {
      const next = { ...prev }
      for (const [sid, buf] of pendingTokens) {
        const ses = next[sid] ?? []
        const last = ses[ses.length - 1]
        if (last?.role !== "assistant") continue
        next[sid] = [...ses.slice(0, -1), {
          ...last,
          content: last.content + buf.content,
          ...(buf.reasoning ? { reasoning: (last.reasoning ?? "") + buf.reasoning } : {}),
        }]
      }
      return next
    })
  })
  pendingTokens.clear()
}

function createStreamCallbacks(sid: string, controller: AbortController): StreamCallbacks {
  return {
    onHistory(snap: HistorySnapshot) {
      // El snapshot ya incluye el contenido en vivo: los tokens en buffer de
      // esta sesión son redundantes y aplicarlos los duplicaría.
      pendingTokens.delete(sid)
      let finalMsgs = snap.messages
      if (snap.agentActive) {
        const liveMsg: ChatMessage = { role: "assistant", content: snap.liveContent }
        if (snap.liveReasoning) liveMsg.reasoning = snap.liveReasoning
        if (snap.liveReportId) liveMsg.reportId = snap.liveReportId
        if (snap.liveReportTitle) liveMsg.reportTitle = snap.liveReportTitle
        finalMsgs = [...snap.messages, liveMsg]
      }
      setMessagesBySession((prev) => ({ ...prev, [sid]: capMessages(finalMsgs) }))
      setStreamState(sid, {
        active: snap.agentActive,
        thinking: snap.agentActive && !snap.liveContent,
      })
      setToolStatusBySession((prev) => ({ ...prev, [sid]: snap.toolStatus }))
    },
    onReasoning(token: string) {
      pendingFor(sid).reasoning += token
      scheduleFlush()
    },
    onToken(token: string) {
      if (streamingBySession()[sid]?.thinking) {
        setStreamState(sid, { thinking: false })
      }
      pendingFor(sid).content += token
      scheduleFlush()
    },
    onUsage(usage: ChatUsage) {
      setUsageBySession((prev) => {
        const existing = prev[sid]
        return {
          ...prev,
          [sid]: {
            prompt_tokens: (existing?.prompt_tokens ?? 0) + (usage.prompt_tokens || 0),
            completion_tokens: (existing?.completion_tokens ?? 0) + (usage.completion_tokens || 0),
            prompt_cache_hit_tokens: (existing?.prompt_cache_hit_tokens ?? 0) + (usage.prompt_cache_hit_tokens || 0),
            prompt_cache_miss_tokens: (existing?.prompt_cache_miss_tokens ?? 0) + (usage.prompt_cache_miss_tokens || 0),
            total_tokens: (existing?.total_tokens ?? 0) + (usage.total_tokens || 0),
          },
        }
      })
    },
    onToolProgress(data: any) {
      // El servidor manda mensaje vacío para limpiar el banner (subagente fallido).
      setToolStatusBySession((prev) => ({ ...prev, [sid]: data?.message || null }))
    },
    onToolEnd(_data: any) {},
    onSubagentEnd(data) {
      flushPendingTokens()
      setToolStatusBySession((prev) => ({ ...prev, [sid]: null }))
      import("../stores/report-store").then((m) => m.loadReport(data.reportId))
      import("../stores/learnit-store").then((ls) => ls.refetchReports())
      setMessagesBySession((prev) => {
        const ses = prev[sid] ?? []
        const updated = [...ses]
        if (updated.length > 0 && updated[updated.length - 1].role === "assistant") {
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            reportId: data.reportId,
            reportTitle: data.title,
          }
        }
        return { ...prev, [sid]: updated }
      })
    },
    onServerError(message: string) {
      flushPendingTokens()
      setStreamState(sid, { thinking: false })
      setErrorBySession((prev) => ({ ...prev, [sid]: message }))
    },
    onDone() {
      return finalizeStream(sid, controller)
    },
    onError(_err: Error) {
      if (streamController === controller) {
        streamController = null
        setStreamState(sid, { active: false, thinking: false })
      }
    },
  }
}

async function finalizeStream(sid: string, controller: AbortController) {
  flushPendingTokens()
  setToolStatusBySession((prev) => ({ ...prev, [sid]: null }))
  try {
    // Reconciliación: el servidor persistió la respuesta completa; recargar
    // absorbe cualquier token perdido por el pub/sub no bloqueante.
    const msgs = await loadFromDB(sid)
    if (msgs.length > 0) {
      setMessagesBySession((prev) => ({ ...prev, [sid]: capMessages(msgs) }))
    }
  } finally {
    setStreamState(sid, { active: false, thinking: false })
    if (streamController === controller) streamController = null
  }
}

const MAX_STREAM_RETRIES = 3

export function subscribeToSession(sid: string, attempt = 0) {
  streamController?.abort()
  const controller = new AbortController()
  streamController = controller

  streamSession(sid, createStreamCallbacks(sid, controller), controller.signal)
    .then(({ completed }) => {
      if (completed || streamController !== controller) return
      // Conexión cortada sin "done" (red, suspensión del equipo): el agente
      // puede seguir vivo en el servidor. Reintentar; el "history" de la
      // reconexión resincroniza todo el estado.
      if (attempt < MAX_STREAM_RETRIES) {
        setTimeout(() => {
          if (streamController === controller) subscribeToSession(sid, attempt + 1)
        }, 1000)
      } else {
        finalizeStream(sid, controller)
      }
    })
    .catch(() => {
      if (streamController === controller) {
        streamController = null
        setStreamState(sid, { active: false, thinking: false })
      }
    })
}

// El propio stream entrega el historial (evento "history"), tanto si hay un
// agente vivo como si la sesión está inactiva (snapshot de DB).
export async function loadSessionMessages(sessionId: string) {
  subscribeToSession(sessionId)
}

export async function sendMessage(content: string) {
  const sid = activeSessionId()
  if (!sid) return
  if (streamingBySession()[sid]?.active) return

  const current = messagesBySession()[sid] ?? []
  const userMsg: ChatMessage = { role: "user", content }
  const messages = [...current, userMsg]
  const withPlaceholder: ChatMessage[] = [...messages, { role: "assistant", content: "" }]

  setErrorBySession((prev) => ({ ...prev, [sid]: null }))
  setStreamState(sid, { active: true, thinking: true })
  setMessagesBySession((prev) => ({ ...prev, [sid]: capMessages(withPlaceholder) }))

  try {
    await startChat(sid, messages)
    broadcastAgentStarted(sid)
  } catch {
    setStreamState(sid, { active: false, thinking: false })
    // Re-sincronizar con el servidor (cubre "agent already running" y rechazos).
    subscribeToSession(sid)
    return
  }

  subscribeToSession(sid)
}

export async function cancelStreaming() {
  const sid = activeSessionId()
  if (!sid) return
  setStreamState(sid, { thinking: false })
  try {
    // El servidor cancela el run, persiste el parcial y emite "done";
    // el stream abierto se cierra solo por esa vía.
    await fetch(`/api/sessions/${encodeURIComponent(sid)}/agent`, { method: "DELETE" })
  } catch {
    streamController?.abort()
    streamController = null
    setStreamState(sid, { active: false, thinking: false })
  }
}
