import { createSignal, createMemo, batch } from "solid-js"
import { createStore } from "solid-js/store"
import { startChat, type ChatMessage, type ChatUsage, type StreamCallbacks, type HistorySnapshot } from "../lib/chat-stream"
import type { ToolEntry } from "../lib/sse-types"
import { activeSessionId, createNewSession } from "./session-store"
import { setTabHidden, activateTab } from "./viewport-tree-store"
import { setSessionAgentId, saveSessionConfigAsync, setSessionSkillId, typewriterSpeed } from "./settings-store"
import { ChatConnection } from "./chat-connection"

export type { ChatMessage, ChatUsage }

export const [messages, setMessages] = createStore<ChatMessage[]>([])

export const [streamingContent, setStreamingContent] = createSignal("")
export const [streamingReasoning, setStreamingReasoning] = createSignal("")
export const [isStreaming, setIsStreaming] = createSignal(false)
export const [isThinking, setIsThinking] = createSignal(false)
export const [pendingLearningSession, setPendingLearningSession] = createSignal<{skill_name: string, skill_id: string} | null>(null)
export const [scrollTick, setScrollTick] = createSignal(0)

const [agentLabels, setAgentLabels] = createSignal<Record<string, string>>({"": "Agent"})

export function agentLabelFor(agentId: string): string {
  return agentLabels()[agentId] ?? agentId
}

fetch("/api/agents")
  .then((r) => (r.ok ? r.json() : {}))
  .then((labels: Record<string, string>) => {
    if (labels && typeof labels === "object") setAgentLabels({ ...labels, "": "Agent" })
  })
  .catch(() => {})

export const [toolEntries, setToolEntries] = createSignal<ToolEntry[]>([])
export const [turnId, setTurnId] = createSignal(0)
export const [chatError, setChatError] = createSignal<string | null>(null)
export const [usage, setUsage] = createSignal<ChatUsage | null>(null)
export const [mainPromptTokens, setMainPromptTokens] = createSignal(0)

export const currentMessages = createMemo(() => activeSessionId() ? messages : ([] as ChatMessage[]))
export const currentToolEntries = createMemo(() => activeSessionId() ? toolEntries() : [])
export const currentChatError = createMemo(() => activeSessionId() ? chatError() : null)
export const sessionUsage = createMemo(() => activeSessionId() ? usage() : null)
export const mainSessionPromptTokens = createMemo(() => activeSessionId() ? mainPromptTokens() : 0)
export const conversationStarted = createMemo(() => messages.length > 0)

let pendingBuffer = ""
let rafId: number | null = null
let lastDrainTime = 0
let inactiveDrainActive = false
let doneDeferred = false
let deferredToolHistory: ToolEntry[] = []
let deferredReports: { reportId: string; reportTitle: string }[] = []

function drainFrame() {
  rafId = null
  if (!pendingBuffer) {
    if (inactiveDrainActive || doneDeferred) {
      inactiveDrainActive = false
      doneDeferred = false
      const content = streamingContent()
      const history = deferredToolHistory
      const reports = deferredReports
      deferredToolHistory = []
      deferredReports = []
      batch(() => {
        if (content) {
          const newMsg: ChatMessage = { role: "assistant", content }
          if (history.length > 0) newMsg.toolHistory = history
          if (reports.length > 0) newMsg.reports = reports
          setMessages((prev: ChatMessage[]) => [...prev, newMsg])
          setStreamingContent("")
        } else if (history.length > 0 || reports.length > 0) {
          if (history.length > 0) {
            const lastIdx = messages.length
            if (lastIdx > 0 && messages[lastIdx - 1].role === "assistant") {
              setMessages(lastIdx - 1, "toolHistory", history)
            } else {
              setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content: "", toolHistory: history }])
            }
          }
          if (reports.length > 0) {
            const lastIdx = messages.length
            if (lastIdx > 0 && messages[lastIdx - 1].role === "assistant") {
              setMessages(lastIdx - 1, "reports", (prev: ChatMessage["reports"]) => [...(prev ?? []), ...reports])
            } else {
              setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content: "", reports }])
            }
          }
        }
        setStreamingReasoning("")
        setIsStreaming(false)
        setToolEntries([])
      })
    }
    return
  }
  const bufferLen = pendingBuffer.length
  const now = performance.now()
  const dt = lastDrainTime ? (now - lastDrainTime) : 16.67
  lastDrainTime = now
  const targetCharsPerMs = typewriterSpeed() * 0.24
  const charsToDrain = Math.max(1, Math.min(Math.ceil(bufferLen * 0.1), Math.ceil(targetCharsPerMs * dt), pendingBuffer.length))
  const chunk = pendingBuffer.slice(0, charsToDrain)
  pendingBuffer = pendingBuffer.slice(charsToDrain)
  batch(() => setStreamingContent(prev => prev + chunk))
  rafId = requestAnimationFrame(drainFrame)
}

function startDrain() {
  if (rafId !== null) return
  rafId = requestAnimationFrame(drainFrame)
}

function stopDrain() {
  lastDrainTime = 0
  inactiveDrainActive = false
  doneDeferred = false
  deferredToolHistory = []
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
    setScrollTick(t => t + 1)
    setToolEntries([])
    setTurnId(n => n + 1)
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
  batch(() => { setIsStreaming(true); setIsThinking(true); setScrollTick(t => t + 1); setToolEntries([]); setTurnId(n => n + 1) })
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
            setToolEntries([])
          })
          pendingBuffer = last.content
          if (snap.liveReports && snap.liveReports.length > 0) {
            deferredReports = snap.liveReports.map(r => ({ reportId: r.reportId, reportTitle: r.reportTitle }))
          }
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
        if (snap.toolLog) {
          setToolEntries(snap.toolLog.map(entry => ({
            id: entry.id,
            agent: entry.agent,
            parentId: entry.parentId ?? null,
            parentAgent: entry.parentAgent ?? null,
            message: entry.message,
            favicons: entry.favicons ?? [],
            done: entry.done,
          })))
        }
      })
      if (snap.liveContent) {
        pendingBuffer = snap.liveContent
        startDrain()
      }
      if (snap.liveReports && snap.liveReports.length > 0) {
        const lastIdx = messages.length
        const mapped = snap.liveReports.map(r => ({ reportId: r.reportId, reportTitle: r.reportTitle }))
        if (lastIdx > 0 && messages[lastIdx - 1].role === "assistant") {
          setMessages(lastIdx - 1, "reports", (prev: ChatMessage["reports"]) => [...(prev ?? []), ...mapped])
        } else {
          setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content: "", reports: mapped }])
        }
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
      const id = data?.id
      if (!id) return
      const msg = data?.message ?? ""
      const hasFavicons = "favicons" in (data ?? {})
      const hasAgent = "agent" in (data ?? {})
      const hasParentId = "parentId" in (data ?? {})
      const hasParentAgent = "parentAgent" in (data ?? {})

      setToolEntries(prev => {
        const existingIdx = prev.findIndex(e => e.id === id)
        if (existingIdx >= 0) {
          const next = [...prev]
          const cur = { ...next[existingIdx] }
          if (msg) cur.message = msg
          if (hasAgent) cur.agent = data.agent ?? ""
          if (hasParentId) cur.parentId = data.parentId ?? null
          if (hasParentAgent) cur.parentAgent = data.parentAgent ?? null
          if (hasFavicons) cur.favicons = data.favicons ?? []
          next[existingIdx] = cur
          return next
        }
        return [...prev, {
          id,
          agent: data?.agent ?? "",
          parentId: data?.parentId ?? null,
          parentAgent: data?.parentAgent ?? null,
          message: msg,
          favicons: data.favicons ?? [],
          done: false,
        }]
      })
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
      // Mark entry as done (find by id; if not found, append a done entry)
      const eId = data.id
      if (eId) {
        setToolEntries(prev => {
          const idx = prev.findIndex(e => e.id === eId)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], done: true, title: data.title ?? undefined, favicons: [] }
            return next
          }
          return [...prev, {
            id: eId,
            agent: data.agent ?? "",
            parentId: data.parentId ?? null,
            parentAgent: data.parentAgent ?? null,
            message: data.summary ?? "",
            favicons: [],
            done: true,
            title: data.title ?? data.summary ?? "",
          }]
        })
      }
      // Only attach report cards for non-internal subagents
      if (data.internal) return
      if (data.reportId) {
        import("../stores/report-store").then(m => m.loadReport(data.reportId!))
      }
      import("../stores/learnit-store").then(ls => ls.refetchReports())
      // Ensure a recent assistant message exists to attach reports to
      let reportTargetIdx = messages.length
      if (reportTargetIdx > 0 && messages[reportTargetIdx - 1].role !== "assistant" && data.reportId) {
        setMessages((prev: ChatMessage[]) => [...prev, { role: "assistant", content: "" }])
        reportTargetIdx = messages.length
        setScrollTick(t => t + 1)
      }
      if (reportTargetIdx > 0 && messages[reportTargetIdx - 1].role === "assistant" && data.reportId) {
        batch(() => {
          setMessages(reportTargetIdx - 1, "reports", (prev: ChatMessage["reports"]) => [
            ...(prev ?? []),
            { reportId: data.reportId!, reportTitle: data.title ?? "" },
          ])
        })
        setScrollTick(t => t + 1)
      }
    },

    onServerError(message: string) {
      stopDrain()
      pendingBuffer = ""
      setToolEntries([])
      setChatError(message)
    },

    onDone() {
      if (inactiveDrainActive) return
      if (pendingBuffer) {
        deferredToolHistory = toolEntries()
        doneDeferred = true
        return
      }
      flushAll()
      const content = streamingContent()
      if (content) {
        const history = toolEntries()
        const newMsg: ChatMessage = { role: "assistant", content }
        if (history.length > 0) newMsg.toolHistory = history
        batch(() => {
          setMessages((prev: ChatMessage[]) => [...prev, newMsg])
          setStreamingContent("")
          setStreamingReasoning("")
          setIsStreaming(false)
          setToolEntries([])
        })
        if (history.length > 0) setScrollTick(t => t + 1)
      } else {
        const history = toolEntries()
        if (history.length > 0) {
          const lastIdx = messages.length
          if (lastIdx > 0 && messages[lastIdx - 1].role === "assistant") {
            batch(() => {
              setMessages(lastIdx - 1, "toolHistory", history)
              setToolEntries([])
            })
          } else {
            const newMsg: ChatMessage = { role: "assistant", content: "", toolHistory: history }
            batch(() => {
              setMessages((prev: ChatMessage[]) => [...prev, newMsg])
              setToolEntries([])
            })
          }
          setScrollTick(t => t + 1)
        } else {
          setToolEntries([])
        }
        setIsStreaming(false)
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
