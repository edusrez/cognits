import { createSignal, batch } from "solid-js"
import { startChat, type ChatMessage, type ChatUsage, type StreamCallbacks, type HistorySnapshot } from "../lib/chat-stream"
import { activeSessionId } from "./session-store"
import { setTabHidden } from "./viewport-tree-store"
import { ChatConnection } from "./chat-connection"

export type { ChatMessage, ChatUsage }

// ── committed messages ───────────────────────────────────────────────────
export const [messages, setMessages] = createSignal<ChatMessage[]>([])

// ── live streaming ───────────────────────────────────────────────────────
export const [streamingContent, setStreamingContent] = createSignal("")
export const [streamingReasoning, setStreamingReasoning] = createSignal("")
export const [isStreaming, setIsStreaming] = createSignal(false)
export const [isThinking, setIsThinking] = createSignal(false)

// ── tool / error / usage ─────────────────────────────────────────────────
export const [toolStatus, setToolStatus] = createSignal<string | null>(null)
export const [toolFavicons, setToolFavicons] = createSignal<string[]>([])
export const [chatError, setChatError] = createSignal<string | null>(null)
export const [usage, setUsage] = createSignal<ChatUsage | null>(null)
export const [mainPromptTokens, setMainPromptTokens] = createSignal(0)

// ── current-session derived ──────────────────────────────────────────────
export const currentMessages = () => activeSessionId() ? messages() : []
export const currentToolStatus = () => activeSessionId() ? toolStatus() : null
export const currentChatError = () => activeSessionId() ? chatError() : null
export const sessionUsage = () => activeSessionId() ? usage() : null
export const mainSessionPromptTokens = () => activeSessionId() ? mainPromptTokens() : 0
export const conversationStarted = () => messages().length > 0

// ── token buffering (50ms fixed batch) ────────────────────────────────────
let tokenBuffer = ""
let flushTimer: ReturnType<typeof setInterval> | null = null

function flushTokens() {
  if (!tokenBuffer) return
  const batch_ = tokenBuffer
  tokenBuffer = ""
  batch(() => setStreamingContent(prev => prev + batch_))
}

function stopFlush() {
  if (flushTimer !== null) {
    clearInterval(flushTimer)
    flushTimer = null
  }
}

function replayTypewriter(text: string) {
  let i = 0
  const timer = setInterval(() => {
    if (i < text.length) {
      batch(() => setStreamingContent(prev => prev + text[i]))
      i++
    } else {
      clearInterval(timer)
      const content = streamingContent() + text.slice(i)
      if (content) {
        batch(() => {
          setMessages(prev => [...prev, { role: "assistant", content }])
          setStreamingContent("")
          setIsStreaming(false)
          setToolStatus(null)
        })
      } else {
        setIsStreaming(false)
        setToolStatus(null)
      }
    }
  }, 20) // 50 chars/sec
}

// ── connection ────────────────────────────────────────────────────────────
const connection = new ChatConnection()

export function loadSessionMessages(sessionId: string): void {
  connection.connect(sessionId, createCallbacks())
}

export function subscribeToSession(sid: string): void {
  connection.connect(sid, createCallbacks())
}

// ── send / cancel ─────────────────────────────────────────────────────────

export async function sendMessage(content: string) {
  const sid = activeSessionId()
  if (!sid || isStreaming()) return
  const cur = messages()
  const userMsg: ChatMessage = { role: "user", content }
  const newMsgs = [...cur, userMsg]

  batch(() => {
    setChatError(null)
    setIsStreaming(true)
    setIsThinking(true)
    setMessages(newMsgs)
  })

  try {
    await startChat(sid, newMsgs)
  } catch (e) {
    setIsStreaming(false)
    setIsThinking(false)
    const msg = e instanceof Error ? e.message : ""
    if (msg === "HTTP 401") {
      setChatError("API key not configured. Please configure it in Settings.")
    }
    subscribeToSession(sid)
    return
  }
  subscribeToSession(sid)
}

export async function sendHiddenMessage(content: string) {
  const sid = activeSessionId()
  if (!sid) return
  batch(() => { setIsStreaming(true); setIsThinking(true) })
  await startChat(sid, [{ role: "hidden_user", content }])
  subscribeToSession(sid)
}

export async function cancelStreaming() {
  const sid = activeSessionId()
  if (!sid) return
  setIsThinking(false)
  try {
    await fetch(`/api/sessions/${encodeURIComponent(sid)}/agent`, { method: "DELETE" })
  } catch {
    connection.disconnect()
    setIsStreaming(false)
  }
}

// ── callbacks ─────────────────────────────────────────────────────────────

function createCallbacks(): StreamCallbacks {
  return {
    onHistory(snap: HistorySnapshot) {
      stopFlush()
      tokenBuffer = ""

      // INACTIVE path: agent already finished.  Replay the assistant response
      // through the typewriter so it doesn't appear all at once.
      if (!snap.agentActive && !snap.liveContent && snap.messages.length) {
        const last = snap.messages[snap.messages.length - 1]
        if (last.role === "assistant" && last.content) {
          const text = last.content
          batch(() => {
            setMessages(snap.messages.slice(0, -1))
            setIsStreaming(true)
            setIsThinking(false)
            setStreamingContent("")
            setStreamingReasoning("")
            setToolStatus(snap.toolStatus)
            if (snap.toolFavicons) setToolFavicons(snap.toolFavicons)
          })
          replayTypewriter(text)
          return
        }
      }

      batch(() => {
        setMessages(snap.messages)
        setIsStreaming(snap.agentActive || !!snap.liveContent)
        setIsThinking(snap.agentActive && !snap.liveContent)
        setStreamingContent(snap.liveContent ?? "")
        setStreamingReasoning(snap.liveReasoning ?? "")
        setToolStatus(snap.toolStatus)
        if (snap.toolFavicons) setToolFavicons(snap.toolFavicons)
      })
    },
    onReasoning(token: string) {
      setStreamingReasoning(prev => prev + token)
    },
    onToken(token: string) {
      if (isThinking()) setIsThinking(false)
      tokenBuffer += token
      if (flushTimer === null) {
        flushTimer = setInterval(flushTokens, 50)
      }
    },
    onUsage(u: ChatUsage) {
      setUsage(prev => ({
        prompt_tokens: (prev?.prompt_tokens ?? 0) + (u.prompt_tokens || 0),
        completion_tokens: (prev?.completion_tokens ?? 0) + (u.completion_tokens || 0),
        prompt_cache_hit_tokens: (prev?.prompt_cache_hit_tokens ?? 0) + (u.prompt_cache_hit_tokens || 0),
        prompt_cache_miss_tokens: (prev?.prompt_cache_miss_tokens ?? 0) + (u.prompt_cache_miss_tokens || 0),
        total_tokens: (prev?.total_tokens ?? 0) + (u.total_tokens || 0),
      }))
      if ((u as any).source === "orchestrator" && u.prompt_tokens) {
        setMainPromptTokens(p => p + u.prompt_tokens!)
      }
    },
    onToolProgress(data: any) {
      setToolStatus(data?.message || null)
      if (data?.favicons) setToolFavicons(data.favicons)
    },
    onToolEnd() {},
    onToolStart() {
      stopFlush()
      const cur = streamingContent()
      const reason = streamingReasoning()
      if (cur) {
        batch(() => {
          setMessages(prev => [...prev, { role: "assistant", content: cur, reasoning: reason || undefined }])
          setStreamingContent("")
          setStreamingReasoning("")
        })
      }
    },
    onSessionRenamed() {
      import("../stores/session-store").then(m => m.loadSessions())
    },
    onSubagentEnd(data) {
      stopFlush()
      const cur = streamingContent()
      if (cur) {
        batch(() => {
          setMessages(prev => [...prev, { role: "assistant", content: cur }])
          setStreamingContent("")
        })
      }
      setToolStatus(null)
      setToolFavicons([])
      import("../stores/report-store").then(m => m.loadReport(data.reportId))
      import("../stores/learnit-store").then(ls => ls.refetchReports())
      setMessages(prev => {
        const updated = [...prev]
        if (updated.length > 0 && updated[updated.length - 1].role === "assistant") {
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            reportId: data.reportId,
            reportTitle: data.title,
          }
        }
        return updated
      })
    },
    onServerError(message: string) {
      stopFlush()
      setChatError(message)
    },
    onDone() {
      stopFlush()
      flushTokens()
      const content = streamingContent()
      if (content) {
        batch(() => {
          setMessages(prev => [...prev, { role: "assistant", content }])
          setStreamingContent("")
          setStreamingReasoning("")
          setIsStreaming(false)
          setToolStatus(null)
        })
      } else {
        setIsStreaming(false)
        setToolStatus(null)
      }
    },
    onError() {
      connection.disconnect()
      setIsStreaming(false)
      setIsThinking(false)
    },
    onUIAction(data: any) {
      if (data?.action === "toggle_tab") {
        setTabHidden(data.viewportId, data.tabId, data.hidden)
      }
    },
  }
}
