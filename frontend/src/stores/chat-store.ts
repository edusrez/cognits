import { createSignal, createMemo, batch } from "solid-js"
import { startChat, streamSession, type ChatMessage, type ChatUsage, type StreamCallbacks, type HistorySnapshot } from "../lib/chat-stream"
import { activeSessionId } from "./session-store"
import { setTabHidden } from "./viewport-tree-store"

export type { ChatMessage, ChatUsage }

// ── committed messages (history) ──────────────────────────────────────────
export const [messages, setMessages] = createSignal<ChatMessage[]>([])

// ── live streaming accumulator (never mutated inside messages[]) ──────────
export const [streamingContent, setStreamingContent] = createSignal("")
export const [streamingReasoning, setStreamingReasoning] = createSignal("")
export const [isStreaming, setIsStreaming] = createSignal(false)
export const [isThinking, setIsThinking] = createSignal(false)

// ── tool / error / usage state ────────────────────────────────────────────
export const [toolStatus, setToolStatus] = createSignal<string | null>(null)
export const [toolFavicons, setToolFavicons] = createSignal<string[]>([])
export const [chatError, setChatError] = createSignal<string | null>(null)
export const [usage, setUsage] = createSignal<ChatUsage | null>(null)
export const [mainPromptTokens, setMainPromptTokens] = createSignal(0)

// Derive current-session values (no per-session maps needed)
const _currentSession = createMemo(() => activeSessionId())

export const currentMessages = createMemo(() => _currentSession() ? messages() : [])
export const currentToolStatus = createMemo(() => _currentSession() ? toolStatus() : null)
export const currentChatError = createMemo(() => _currentSession() ? chatError() : null)
export const sessionUsage = createMemo(() => _currentSession() ? usage() : null)
export const mainSessionPromptTokens = createMemo(() => _currentSession() ? mainPromptTokens() : 0)
export const conversationStarted = createMemo(() => messages().length > 0)

// ── SSE connection ────────────────────────────────────────────────────────
let streamController: AbortController | null = null

const MAX_STREAM_RETRIES = 3

export function subscribeToSession(sid: string, attempt: number = 0) {
  streamController?.abort()
  const controller = new AbortController()
  streamController = controller

  streamSession(sid, createStreamCallbacks(controller), controller.signal)
    .then(({ completed }) => {
      if (completed || streamController !== controller) return
      if (attempt < MAX_STREAM_RETRIES) {
        setTimeout(() => {
          if (streamController === controller) subscribeToSession(sid, attempt + 1)
        }, 1000)
      } else {
        finalizeStream(controller)
      }
    })
    .catch(() => {
      if (streamController === controller) {
        streamController = null
        setIsStreaming(false)
        setIsThinking(false)
      }
    })
}

export function loadSessionMessages(sessionId: string) {
  subscribeToSession(sessionId)
}

// ── sending messages ──────────────────────────────────────────────────────

export async function sendMessage(content: string) {
  const sid = activeSessionId()
  if (!sid) return
  if (isStreaming()) return

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
  batch(() => {
    setIsStreaming(true)
    setIsThinking(true)
  })
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
    streamController?.abort()
    streamController = null
    setIsStreaming(false)
  }
}

// ── write buffer + adaptive rAF drain ──────────────────────────────────
// Tokens accumulate here (non-reactive). The drain speed adapts to the
// buffer depth: fast (~500 chars/s) when full, slow (~50 chars/s) when
// nearly empty — preserving a typewriter effect all the way to the end.
// On "done" the buffer drains to empty, then commits atomically.

let writeBuffer = ""
let rafId: number | null = null
let lastFrameTime = 0
let streamEnding = false

const MIN_BUFFER = 20   // chars — below this, switch to slow pace
const SLOW_MS = 20      // ms/char in slow mode (~50 chars/s)
const FAST_MS = 2       // ms/char in fast mode  (~500 chars/s)

function drainBuffer(now: number) {
  const elapsed = lastFrameTime ? now - lastFrameTime : 16.67
  lastFrameTime = now

  const msPerChar = writeBuffer.length >= MIN_BUFFER ? FAST_MS : SLOW_MS
  const count = Math.max(1, Math.floor(elapsed / msPerChar))
  const chunk = writeBuffer.slice(0, count)
  writeBuffer = writeBuffer.slice(chunk.length)

  if (chunk) {
    batch(() => setStreamingContent(prev => prev + chunk))
  }

  if (writeBuffer.length > 0) {
    rafId = requestAnimationFrame(drainBuffer)
  } else if (streamEnding) {
    streamEnding = false
    rafId = null
    commitStream()
  } else {
    rafId = null
  }
}

function startDrain() {
  if (rafId !== null) return
  lastFrameTime = 0
  rafId = requestAnimationFrame(drainBuffer)
}

function flushBuffer() {
  if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null }
  if (writeBuffer) {
    batch(() => setStreamingContent(prev => prev + writeBuffer))
    writeBuffer = ""
  }
}

function commitStream() {
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
}

// ── SSE callbacks ─────────────────────────────────────────────────────────

function createStreamCallbacks(controller: AbortController): StreamCallbacks {
  return {
    onHistory(snap: HistorySnapshot) {
      streamEnding = false
      if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null }
      writeBuffer = snap.liveContent ?? ""
      const finalMsgs = snap.messages
      batch(() => {
        setMessages(finalMsgs)
        setIsStreaming(snap.agentActive)
        setIsThinking(snap.agentActive && !snap.liveContent)
        setStreamingContent("")
        setStreamingReasoning(snap.liveReasoning ?? "")
        setToolStatus(snap.toolStatus)
        if (snap.toolFavicons) setToolFavicons(snap.toolFavicons)
      })
      if (writeBuffer) startDrain()
    },
    onReasoning(token: string) {
      setStreamingReasoning(prev => prev + token)
    },
    onToken(token: string) {
      if (isThinking()) setIsThinking(false)
      writeBuffer += token
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
      // Commit current streaming content as a completed message,
      // start a fresh accumulator for post-tool content.
      flushBuffer()
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
      flushBuffer()
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
      flushBuffer()
      setChatError(message)
    },
    onDone() {
      streamEnding = true
      if (writeBuffer.length === 0) commitStream()
    },
    onError() {
      if (streamController === controller) {
        streamController = null
        setIsStreaming(false)
        setIsThinking(false)
      }
    },
    onUIAction(data: any) {
      if (data?.action === "toggle_tab") {
        setTabHidden(data.viewportId, data.tabId, data.hidden)
      }
    },
  }
}

async function finalizeStream(controller: AbortController) {
  // Safety net for retry timeout / connection loss.
  // Normal stream end goes through onDone → natural drain → commitStream.
  if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null }
  const remaining = writeBuffer
  writeBuffer = ""
  const content = streamingContent() + remaining
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
  if (streamController === controller) streamController = null
}
