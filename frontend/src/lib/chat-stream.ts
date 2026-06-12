export interface ChatMessage {
  role: "user" | "assistant" | "system"
  content: string
  reasoning?: string
  reportId?: string
  reportTitle?: string
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
  /** Error emitido por el agente en el servidor (run fallido). */
  onServerError?: (message: string) => void
  onToolStart?: (data: any) => void
  onToolProgress?: (data: any) => void
  onToolEnd?: (data: any) => void
  onSubagentEnd?: (data: SubagentEndData) => void
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

// Resuelve {completed: true} si el servidor cerró el stream con su evento
// "done" (o tras un error HTTP ya notificado); {completed: false} si la
// conexión se cortó a mitad — el caller puede reintentar la suscripción.
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
              callbacks.onServerError?.(json.message || "Error desconocido")
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
            case "usage":
              callbacks.onUsage(json)
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

  // La conexión terminó sin "done": no finalizar aquí; el caller decide si
  // reintenta (el agente puede seguir vivo en el servidor).
  return { completed: false }
}
