import { createSignal, createMemo, batch } from "solid-js"
import { createStore } from "solid-js/store"
import { startChat, type ChatMessage, type ChatUsage, type StreamCallbacks, type HistorySnapshot } from "../lib/chat-stream"
import { activeSessionId, createNewSession } from "./session-store"
import { setTabHidden, activateTab } from "./viewport-tree-store"
import { setSessionAgentId, saveSessionConfigAsync, setSessionSkillId } from "./settings-store"
import { ChatConnection } from "./chat-connection"

export type { ChatMessage, ChatUsage }

export const [messages, setMessages] = createStore<ChatMessage[]>([])

export const [streamingContent, setStreamingContent] = createSignal("")
export const [streamingReasoning, setStreamingReasoning] = createSignal("")
export const [isStreaming, setIsStreaming] = createSignal(false)
export const [isThinking, setIsThinking] = createSignal(false)
export const [pendingLearningSession, setPendingLearningSession] = createSignal<{skill_name: string, skill_id: string} | null>(null)

const [agentLabels, setAgentLabels] = createSignal<Record<string, string>>({"": "Agent"})

fetch("/api/agents")
  .then((r) => (r.ok ? r.json() : {}))
  .then((labels: Record<string, string>) => {
    if (labels && typeof labels === "object") setAgentLabels({ ...labels, "": "Agent" })
  })
  .catch(() => {})

export const [toolStatus, setToolStatus] = createSignal<Record<string, string>>({})
export const [toolFaviconsByAgent, setToolFaviconsByAgent] = createSignal<Record<string, string[]>>({})
export const [chatError, setChatError] = createSignal<string | null>(null)
export const [usage, setUsage] = createSignal<ChatUsage | null>(null)
export const [mainPromptTokens, setMainPromptTokens] = createSignal(0)

export const currentMessages = createMemo(() => activeSessionId() ? messages : ([] as ChatMessage[]))
export const currentToolStatus = createMemo(() => activeSessionId() ? toolStatus() : {})
export const currentFavicons = createMemo(() => activeSessionId() ? toolFaviconsByAgent() : {})
export const currentChatError = createMemo(() => activeSessionId() ? chatError() : null)
export const sessionUsage = createMemo(() => activeSessionId() ? usage() : null)
export const mainSessionPromptTokens = createMemo(() => activeSessionId() ? mainPromptTokens() : 0)
export const conversationStarted = createMemo(() => messages.length > 0)

let pendingBuffer = ""
let rafId: number | null = null
let lastDrainTime = 0
let inactiveDrainActive = false
let doneDeferred = false

function drainFrame() {
  rafId = null
  if (!pendingBuffer) {
    if (inactiveDrainActive || doneDeferred) {
      inactiveDrainActive = false
      doneDeferred = false
      const content = streamingContent()
      batch(() => {
        if (content) {
          setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content }])
          setStreamingContent("")
        }
        setStreamingReasoning("")
        setIsStreaming(false)
        setToolStatus({}); setToolFaviconsByAgent({})
      })
    }
    return
  }
  const bufferLen = pendingBuffer.length
  const now = performance.now()
  const dt = lastDrainTime ? (now - lastDrainTime) : 16.67
  lastDrainTime = now
  const targetCharsPerMs = 1.2
  const charsToDrain = Math.max(1, Math.min(Math.ceil(bufferLen * 0.1), Math.ceil(targetCharsPerMs * dt), pendingBuffer.length))
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
  lastDrainTime = 0
  inactiveDrainActive = false
  doneDeferred = false
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

export async function flushPendingLearningSession() {
  const pending = pendingLearningSession()
  if (!pending) return
  setPendingLearningSession(null)
  const session = await createNewSession()
  setSessionAgentId("maestro")
  setSessionSkillId(pending.skill_id)
  await saveSessionConfigAsync(session.id)
  // Kick off the Maestro after a brief delay to let loadSessionConfig
  // complete on the new activeSessionId (same pattern as onboarding).
  setTimeout(() => {
    sendHiddenMessage(
      "Start teaching this skill now. Follow the pedagogical plan in your " +
      "system prompt. Begin with Stage 1 and use the Socratic method. " +
      "Respond in the user's language."
    )
  }, 200)
}

function createCallbacks(): StreamCallbacks {
  return {
    onHistory(snap: HistorySnapshot) {
      stopDrain()
      pendingBuffer = ""

      if (!snap.agentActive && !snap.liveContent && snap.messages.length > 0) {
        const last = snap.messages[snap.messages.length - 1]
        if (last.role === "assistant" && last.content) {
          const rest = snap.messages.slice(0, -1)
          batch(() => {
            setMessages(rest)
            setIsStreaming(true)
            setIsThinking(false)
            setStreamingContent("")
            setStreamingReasoning("")
            setToolStatus({})
            setToolFaviconsByAgent({})
          })
          pendingBuffer = last.content
          inactiveDrainActive = true
          startDrain()
          return
        }
      }

      batch(() => {
        setMessages(snap.messages)
        setIsStreaming(snap.agentActive || !!snap.liveContent)
        setIsThinking(snap.agentActive && !snap.liveContent)
        setStreamingContent("")
        setStreamingReasoning(snap.liveReasoning ?? "")
        if (snap.toolStatus) setToolStatus({ Agent: snap.toolStatus })
        if (snap.toolFavicons) setToolFaviconsByAgent({ Agent: snap.toolFavicons })
      })
      if (snap.liveContent) {
        pendingBuffer = snap.liveContent
        startDrain()
      }
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
      const agent = agentLabels()[data?.agent] ?? data?.agent ?? "Agent"
      const msg = data?.message || ""
      const favicons = data?.favicons
      if (msg) {
        setToolStatus(prev => {
          const next = { ...prev }
          next[agent] = msg
          return next
        })
      }
      if (Array.isArray(favicons)) {
        setToolFaviconsByAgent(prev => ({ ...prev, [agent]: favicons }))
      }
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
      setToolStatus({}); setToolFaviconsByAgent({})
      import("../stores/report-store").then(m => m.loadReport(data.reportId))
      import("../stores/learnit-store").then(ls => ls.refetchReports())
      const len = messages.length
      if (len > 0 && messages[len - 1].role === "assistant") {
        batch(() => {
          setMessages(len - 1, "reports", (prev: ChatMessage["reports"]) => [
            ...(prev ?? []),
            { reportId: data.reportId, reportTitle: data.title },
          ])
        })
      }
    },

    onServerError(message: string) {
      stopDrain()
      pendingBuffer = ""
      setToolStatus({}); setToolFaviconsByAgent({})
      setChatError(message)
    },

    onDone() {
      if (inactiveDrainActive) return
      if (pendingBuffer) {
        doneDeferred = true
        return
      }
      flushAll()
      const content = streamingContent()
      if (content) {
        batch(() => {
          setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content }])
          setStreamingContent("")
          setStreamingReasoning("")
          setIsStreaming(false)
          setToolStatus({}); setToolFaviconsByAgent({})
        })
      } else {
        setIsStreaming(false)
        setToolStatus({}); setToolFaviconsByAgent({})
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

    onSetupComplete() {
      setTabHidden("1101", "write", true)
      setTabHidden("1101", "setup", false)
      activateTab("1101", "setup")
      import("../stores/setup-store").then(m => {
        m.setSetupStep("done")
      })
    },
    onCreateLearningSession(data: { skill_name: string, skill_id: string }) {
      setPendingLearningSession({skill_name: data.skill_name, skill_id: data.skill_id})
    },
  }
}
