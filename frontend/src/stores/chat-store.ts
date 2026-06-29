import { createSignal, createMemo, batch } from "solid-js"
import { createStore } from "solid-js/store"
import { startChat, type ChatMessage, type ChatUsage, type StreamCallbacks, type HistorySnapshot } from "../lib/chat-stream"
import { activeSessionId } from "./session-store"
import { setTabHidden } from "./viewport-tree-store"
import { ChatConnection } from "./chat-connection"

export type { ChatMessage, ChatUsage }

export const [messages, setMessages] = createStore<ChatMessage[]>([])

export const [streamingContent, setStreamingContent] = createSignal("")
export const [streamingReasoning, setStreamingReasoning] = createSignal("")
export const [isStreaming, setIsStreaming] = createSignal(false)
export const [isThinking, setIsThinking] = createSignal(false)

export const [toolStatus, setToolStatus] = createSignal<string | null>(null)
export const [toolFavicons, setToolFavicons] = createSignal<string[]>([])
export const [chatError, setChatError] = createSignal<string | null>(null)
export const [usage, setUsage] = createSignal<ChatUsage | null>(null)
export const [mainPromptTokens, setMainPromptTokens] = createSignal(0)

export const currentMessages = createMemo(() => activeSessionId() ? messages : ([] as ChatMessage[]))
export const currentToolStatus = createMemo(() => activeSessionId() ? toolStatus() : null)
export const currentChatError = createMemo(() => activeSessionId() ? chatError() : null)
export const sessionUsage = createMemo(() => activeSessionId() ? usage() : null)
export const mainSessionPromptTokens = createMemo(() => activeSessionId() ? mainPromptTokens() : 0)
export const conversationStarted = createMemo(() => messages.length > 0)

let pendingBuffer = ""
let rafId: number | null = null

function drainFrame() {
  rafId = null
  if (!pendingBuffer) return
  const bufferLen = pendingBuffer.length
  const charsToDrain = Math.max(1, Math.min(Math.ceil(bufferLen * 0.1), 20))
  const chunk = pendingBuffer.slice(0, charsToDrain)
  pendingBuffer = pendingBuffer.slice(charsToDrain)
  batch(() => setStreamingContent(prev => prev + chunk))
  if (pendingBuffer) {
    rafId = requestAnimationFrame(drainFrame)
  }
}

function startDrain() {
  if (rafId !== null) return
  rafId = requestAnimationFrame(drainFrame)
}

function stopDrain() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

function flushAll() {
  stopDrain()
  if (!pendingBuffer) return
  const chunk = pendingBuffer
  pendingBuffer = ""
  batch(() => setStreamingContent(prev => prev + chunk))
}

const connection = new ChatConnection()

export function loadSessionMessages(sessionId: string): void {
  connection.connect(sessionId, createCallbacks())
}

export function subscribeToSession(sid: string): void {
  connection.connect(sid, createCallbacks())
}

export async function sendMessage(content: string) {
  const sid = activeSessionId()
  if (!sid || isStreaming()) return

  const cur = [...messages]
  const userMsg: ChatMessage = { role: "user", content }
  batch(() => {
    setChatError(null)
    setIsStreaming(true)
    setIsThinking(true)
    setMessages([...cur, userMsg])
  })

  try {
    await startChat(sid, [...cur, userMsg])
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
  try {
    await startChat(sid, [{ role: "hidden_user", content }])
  } catch (e) {
    setIsStreaming(false)
    setIsThinking(false)
    const msg = e instanceof Error ? e.message : ""
    if (msg === "HTTP 401") {
      setChatError("API key not configured. Please configure it in Settings.")
    }
    return
  }
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

function createCallbacks(): StreamCallbacks {
  return {
    onHistory(snap: HistorySnapshot) {
      stopDrain()
      pendingBuffer = ""

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
      pendingBuffer += token
      startDrain()
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
      flushAll()
      const content = streamingContent()
      const reason = streamingReasoning()
      if (content) {
        batch(() => {
          setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content, reasoning: reason || undefined }])
          setStreamingContent("")
          setStreamingReasoning("")
        })
      }
    },

    onSessionRenamed() {
      import("../stores/session-store").then(m => m.loadSessions())
    },

    onSubagentEnd(data) {
      flushAll()
      const content = streamingContent()
      if (content) {
        batch(() => {
          setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content }])
          setStreamingContent("")
        })
      }
      setToolStatus(null)
      setToolFavicons([])
      import("../stores/report-store").then(m => m.loadReport(data.reportId))
      import("../stores/learnit-store").then(ls => ls.refetchReports())
      const len = messages.length
      if (len > 0 && messages[len - 1].role === "assistant") {
        batch(() => {
          setMessages(len - 1, "reportId", data.reportId)
          setMessages(len - 1, "reportTitle", data.title)
        })
      }
    },

    onServerError(message: string) {
      stopDrain()
      pendingBuffer = ""
      setChatError(message)
    },

    onDone() {
      flushAll()
      const content = streamingContent()
      if (content) {
        batch(() => {
          setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content }])
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
