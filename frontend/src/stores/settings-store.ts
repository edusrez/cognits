import { createSignal, createMemo } from "solid-js"
import type { ViewportId } from "../tabs"
import type { LLMConfig, SessionConfig } from "../types"
import { activeSessionId } from "./session-store"

export const [linkingMode, setLinkingMode] = createSignal(false)
export const [linkedViewport, setLinkedViewport] =
  createSignal<ViewportId | null>("1100")

export const [hiddenBasicTabs, setHiddenBasicTabs] = createSignal(
  new Set<string>(),
)

export function toggleBasicTab(tabId: string) {
  setHiddenBasicTabs((prev) => {
    const next = new Set(prev)
    next.has(tabId) ? next.delete(tabId) : next.add(tabId)
    return next
  })
}

export const [defaultChatViewport, setDefaultChatViewport] =
  createSignal<ViewportId>("1100")

export const [defaultWriteViewport, setDefaultWriteViewport] =
  createSignal<ViewportId>("1101")
export const [defaultLearnitViewport, setDefaultLearnitViewport] =
  createSignal<ViewportId>("1100")

export const [llmProvider, setLLMProvider] =
  createSignal<LLMConfig["llmProvider"]>("deepseek")
export const [llmAgentId, setLLMAgentId] = createSignal("orquestador")
export const [llmApiKey, setLLMApiKey] = createSignal("")
export const [llmModel, setLLMModel] =
  createSignal<LLMConfig["llmModel"]>("deepseek-v4-pro")
export const [llmReasoning, setLLMReasoning] =
  createSignal<LLMConfig["llmReasoning"]>("max")
export const [agentOverrides, setAgentOverrides] =
  createSignal<Record<string, string>>({})
export const [chatFontSize, setChatFontSize] = createSignal(13)
export const [tinyfishApiKey, setTinyfishApiKey] = createSignal("")
export const [tinyfishTier, setTinyfishTier] = createSignal("payg")
export const [subagentConfig, setSubagentConfig] = createSignal<
  Record<string, { model: string; reasoning: string; maxSteps: number }>
>({})
export const [userName, setUserName] = createSignal("")
export const [userLocation, setUserLocation] = createSignal("")
export const [writeLangs, setWriteLangs] = createSignal<string[]>(["es"])

export const [sessionProvider, setSessionProvider] = createSignal("")
export const [sessionModel, setSessionModel] = createSignal("")
export const [sessionReasoning, setSessionReasoning] = createSignal("")
export const [sessionAgentId, setSessionAgentId] = createSignal("")

export const activeProvider = createMemo(() => {
  const sid = activeSessionId()
  if (sid && sessionProvider()) return sessionProvider()
  return llmProvider()
})
export const activeModel = createMemo(() => {
  const sid = activeSessionId()
  if (sid && sessionModel()) return sessionModel()
  return llmModel()
})
export const activeReasoning = createMemo(() => {
  const sid = activeSessionId()
  if (sid && sessionReasoning()) return sessionReasoning()
  return llmReasoning()
})
export const activeAgentId = createMemo(() => {
  const sid = activeSessionId()
  if (sid && sessionAgentId()) return sessionAgentId()
  return llmAgentId()
})

export async function loadSessionConfig(sessionId: string) {
  const res = await fetch(`/api/sessions/${sessionId}/config`)
  if (!res.ok) return
  const cfg: SessionConfig = await res.json()
  if (cfg.provider) setSessionProvider(cfg.provider)
  if (cfg.model) setSessionModel(cfg.model)
  if (cfg.reasoning) setSessionReasoning(cfg.reasoning)
  if (cfg.agentId) setSessionAgentId(cfg.agentId)
}

export function saveSessionConfig(sessionId: string) {
  fetch(`/api/sessions/${sessionId}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: sessionProvider(),
      model: sessionModel(),
      reasoning: sessionReasoning(),
      agentId: sessionAgentId(),
    }),
  }).catch((err) => console.error("save session config:", err))
}

let saveTimer: ReturnType<typeof setTimeout> | null = null

export async function loadConfig() {
  const res = await fetch("/api/config")
  if (res.ok) {
    const cfg: LLMConfig = await res.json()
    if (cfg.llmProvider) setLLMProvider(cfg.llmProvider)
    if (cfg.llmAgentId) setLLMAgentId(cfg.llmAgentId)
    if (cfg.llmApiKey) setLLMApiKey(cfg.llmApiKey)
    if (cfg.llmModel) setLLMModel(cfg.llmModel)
    if (cfg.llmReasoning) setLLMReasoning(cfg.llmReasoning)
    if (cfg.agentOverrides) setAgentOverrides(cfg.agentOverrides)
    if (cfg.chatFontSize) setChatFontSize(cfg.chatFontSize)
    if (cfg.tinyfishApiKey) setTinyfishApiKey(cfg.tinyfishApiKey)
    if (cfg.tinyfishTier) setTinyfishTier(cfg.tinyfishTier)
    if (cfg.subagentConfig) setSubagentConfig(cfg.subagentConfig)
    if (cfg.userName) setUserName(cfg.userName)
    if (cfg.userLocation) setUserLocation(cfg.userLocation)
    if (cfg.defaultLearnitViewport) setDefaultLearnitViewport(cfg.defaultLearnitViewport)
    if (cfg.writeLangs) setWriteLangs(cfg.writeLangs)
  }
}

export function saveConfig() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(async () => {
    try {
      await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llmProvider: llmProvider(),
          llmAgentId: llmAgentId(),
          llmApiKey: llmApiKey(),
          llmModel: llmModel(),
          llmReasoning: llmReasoning(),
          agentOverrides: agentOverrides(),
          chatFontSize: chatFontSize(),
          tinyfishApiKey: tinyfishApiKey(),
          tinyfishTier: tinyfishTier(),
          subagentConfig: subagentConfig(),
          userName: userName(),
          userLocation: userLocation(),
          defaultLearnitViewport: defaultLearnitViewport(),
          writeLangs: writeLangs(),
        }),
      })
    } catch (err) {
      console.error("save config:", err)
    }
  }, 500)
}
