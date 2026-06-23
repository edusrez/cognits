import { createSignal, createMemo, batch } from "solid-js"
import { startChat, streamSession, type ChatMessage, type ChatUsage, type StreamCallbacks, type HistorySnapshot } from "../lib/chat-stream"
import { activeSessionId } from "./session-store"
import { setTabHidden } from "./viewport-tree-store"

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

// Main-agent prompt tokens only (source === "orchestrator"), excluding subagents.
export const [mainPromptTokensBySession, setMainPromptTokensBySession] = createSignal<
  Record<string, number>
>({})

export const [toolStatusBySession, setToolStatusBySession] = createSignal<
  Record<string, string | null>
>({})

export const [toolFaviconsBySession, setToolFaviconsBySession] = createSignal<
  Record<string, string[]>
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

/** True once the active session has at least one message — used to lock
 *  settings that can't change mid-conversation. */
export const conversationStarted = createMemo(() => currentMessages().length > 0)

export const mainSessionPromptTokens = createMemo(() => {
  const sid = activeSessionId()
  if (!sid) return 0
  return mainPromptTokensBySession()[sid] ?? 0
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

// A single active stream across the app: subscribing to a session always
// aborts the previous stream (prevents duplicate tokens with two readers).
let streamController: AbortController | null = null

// SSE tokens accumulate here and are applied to the store in ~50ms batches:
// updating the signal per token re-renders the entire chat dozens of times
// per second. setTimeout, not rAF: in background tabs rAF freezes and the
// buffer would grow unbounded.
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
      // The snapshot already includes live content: buffered tokens for
      // this session are redundant and applying them would duplicate.
      pendingTokens.delete(sid)
      let finalMsgs = snap.messages.filter(
        (m) => !m.tags?.includes("hidden"),
      )
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
      if (snap.toolFavicons)
        setToolFaviconsBySession((prev) => ({ ...prev, [sid]: snap.toolFavicons! }))
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
      // Accumulate prompt tokens for the main agent only (exclude subagents).
      if ((usage as any).source === "orchestrator" && usage.prompt_tokens) {
        setMainPromptTokensBySession((prev) => ({
          ...prev,
          [sid]: (prev[sid] ?? 0) + usage.prompt_tokens,
        }))
      }
    },
    onToolProgress(data: any) {
      setToolStatusBySession((prev) => ({ ...prev, [sid]: data?.message || null }))
      if (data?.favicons) {
        setToolFaviconsBySession((prev) => ({ ...prev, [sid]: data.favicons }))
      }
    },
    onToolEnd(_data: any) {},
    onSessionRenamed(_data: { name: string }) {
      import("../stores/session-store").then((m) => m.loadSessions())
    },
    onSubagentEnd(data) {
      flushPendingTokens()
      setToolStatusBySession((prev) => ({ ...prev, [sid]: null }))
      setToolFaviconsBySession((prev) => ({ ...prev, [sid]: [] }))
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
    onUIAction(data: any) {
      if (data?.action === "toggle_tab") {
        setTabHidden(data.viewportId, data.tabId, data.hidden)
      }
    },
  }
}

async function finalizeStream(sid: string, controller: AbortController) {
  flushPendingTokens()
  setToolStatusBySession((prev) => ({ ...prev, [sid]: null }))
  try {
    // Reconciliation: the server persisted the full response to DB;
    // reloading absorbs any tokens lost by non-blocking pub/sub.
    // Only replace messages where the DB has MORE content than the
    // frontend — never overwrite recently flushed tokens with a
    // stale DB snapshot.
    const dbMsgs = await loadFromDB(sid)
    if (dbMsgs.length > 0) {
      setMessagesBySession((prev) => {
        const current = prev[sid] ?? []
        const reconciled = dbMsgs.map((dbMsg, i) => {
          const cur = current[i]
          if (!cur) return dbMsg
          if (dbMsg.content.length > cur.content.length) return dbMsg
          return cur
        })
        return { ...prev, [sid]: capMessages(reconciled) }
      })
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
      // Connection cut without "done" (network, machine sleep): the agent
      // may still be alive on the server. Retry; the reconnection "history"
      // resynchronizes all state.
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

// The stream itself delivers the history ("history" event), whether there's a
// live agent or the session is inactive (DB snapshot).
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
  } catch (e) {
    setStreamState(sid, { active: false, thinking: false })
    const msg = e instanceof Error ? e.message : ""
    if (msg === "HTTP 401") {
      setErrorBySession((prev) => ({ ...prev, [sid]: "API key not configured. Please configure it in Settings." }))
    }
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
    // The server cancels the run, persists the partial, and emits "done";
    // the open stream closes on its own via that path.
    await fetch(`/api/sessions/${encodeURIComponent(sid)}/agent`, { method: "DELETE" })
  } catch {
    streamController?.abort()
    streamController = null
    setStreamState(sid, { active: false, thinking: false })
  }
}

export async function sendHiddenMessage(content: string) {
  const sid = activeSessionId()
  if (!sid) return
  setStreamState(sid, { active: true, thinking: true })
  await startChat(sid, [{ role: "user", content, tags: ["hidden"] }])
  subscribeToSession(sid)
}
