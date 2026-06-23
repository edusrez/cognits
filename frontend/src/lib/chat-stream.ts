export interface ChatMessage {
  role: "user" | "assistant" | "system"
  content: string
  reasoning?: string
  reportId?: string
  reportTitle?: string
  tags?: string[]
}

export interface ChatUsage {
  prompt_tokens: number
  completion_tokens: number
  prompt_cache_hit_tokens: number
  prompt_cache_miss_tokens: number
  total_tokens?: number
}

export interface SubagentEndData {
  reportId: string
  title: string
  summary: string
}

export interface HistorySnapshot {
  messages: ChatMessage[]
  toolStatus: string | null
  toolFavicons?: string[]
  liveContent: string
  liveReasoning: string
  liveReportId: string
  liveReportTitle: string
  agentActive: boolean
}

export interface StreamCallbacks {
  onToken: (token: string) => void
  onReasoning: (token: string) => void
  onUsage: (usage: ChatUsage) => void
  onHistory: (snapshot: HistorySnapshot) => void
  onDone: () => void
  onError: (error: Error) => void
  /** Error emitted by the agent on the server (failed run). */
  onServerError?: (message: string) => void
  onToolStart?: (data: any) => void
  onToolProgress?: (data: any) => void
  onToolEnd?: (data: any) => void
  onSubagentEnd?: (data: SubagentEndData) => void
  onSessionRenamed?: (data: { name: string }) => void
  onUIAction?: (data: any) => void
}

export async function startChat(sessionId: string, messages: ChatMessage[]): Promise<void> {
  const res = await fetch(`/api/chat?sessionId=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  })
  if (res.status === 409) {
    throw new Error("agent_already_running")
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`)
  }
}

// Resolves {completed: true} if the server closed the stream with its
// "done" event (or after a previously notified HTTP error); {completed: false}
// if the connection was cut mid-stream — the caller can retry the subscription.
export async function streamSession(
  sessionId: string,
  callbacks: StreamCallbacks,
  abortSignal?: AbortSignal,
): Promise<{ completed: boolean }> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/stream`, {
    signal: abortSignal,
  })

  if (!response.ok) {
    callbacks.onError(new Error(`HTTP ${response.status}`))
    return { completed: true }
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let currentEvent = "message"

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split("\n\n")
    buffer = events.pop() || ""

    for (const event of events) {
      const lines = event.split("\n")
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7)
          continue
        }
        if (!line.startsWith("data: ")) continue
        const data = line.slice(6)

        try {
          const json = JSON.parse(data)

          if (currentEvent === "history") {
            callbacks.onHistory({
              messages: json.messages || [],
              toolStatus: json.toolStatus || null,
              liveContent: json.liveContent || "",
              liveReasoning: json.liveReasoning || "",
              liveReportId: json.liveReportId || "",
              liveReportTitle: json.liveReportTitle || "",
              agentActive: json.agentActive === true,
            })
            continue
          }

          if (currentEvent === "done") {
            callbacks.onDone()
            return { completed: true }
          }

          switch (currentEvent) {
            case "reasoning":
              callbacks.onReasoning(json.content || "")
              break
            case "error":
              callbacks.onServerError?.(json.message || "Unknown error")
              break
            case "tool_start":
              callbacks.onToolStart?.(json)
              break
            case "tool_progress":
              callbacks.onToolProgress?.(json)
              break
            case "tool_end":
              callbacks.onToolEnd?.(json)
              break
            case "subagent_end":
              callbacks.onSubagentEnd?.(json)
              break
            case "session_renamed":
              callbacks.onSessionRenamed?.(json)
              break
            case "usage":
              callbacks.onUsage(json)
              break
            case "ui_action":
              callbacks.onUIAction?.(json)
              break
              break
            default: {
              const content = json.choices?.[0]?.delta?.content
              const reasoning = json.choices?.[0]?.delta?.reasoning_content
              if (reasoning) callbacks.onReasoning(reasoning)
              if (content) callbacks.onToken(content)
              if (json.usage) callbacks.onUsage(json.usage)
            }
          }
        } catch {
          // skip unparseable chunks
        }
      }
      currentEvent = "message"
    }
  }

  // Connection ended without "done": don't finalize here; the caller decides
  // whether to retry (the agent may still be alive on the server).
  return { completed: false }
}
