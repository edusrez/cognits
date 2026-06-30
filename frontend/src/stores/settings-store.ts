import { createSignal, createMemo } from "solid-js"
import type { ViewportId } from "../tabs"
import type { AgentDef, LLMConfig, SessionConfig, SubagentConfig } from "../types"
import { activeSessionId } from "./session-store"
import { sessionUsage } from "./chat-store"
import { resolveViewportLink, onViewportReplaced, getViewportData,
  storedLinkedViewport, setLinkedViewport,
  storedDefaultChatViewport, setDefaultChatViewport,
  storedDefaultWriteViewport, setDefaultWriteViewport,
  storedDefaultLearnitViewport, setDefaultLearnitViewport,
  storedDefaultFilesViewport, setDefaultFilesViewport,
} from "./viewport-tree-store"

// ── Pricing + token-cost helpers (used by the Chat Info section) ──
export const PRICES: Record<string, { inputCacheHit: number; inputCacheMiss: number; output: number }> = {
  "deepseek-v4-flash": { inputCacheHit: 0.0028, inputCacheMiss: 0.14, output: 0.28 },
  "deepseek-v4-pro": { inputCacheHit: 0.003625, inputCacheMiss: 0.435, output: 0.87 },
}

export function formatCost(tokens: number, pricePerM: number): string {
  return "$" + ((tokens / 1_000_000) * pricePerM).toFixed(2)
}

export function formatNumber(n: number): string {
  return n.toLocaleString()
}

export const [linkingMode, setLinkingMode] = createSignal(false)

// ── Viewport links ──
// Each link stores the user's intended viewport id (storedX in viewport-tree-store)
// and exposes a lazy-resolve function (X) that returns a viewport that currently
// exists. storedX are migrated by splitViewport/deleteViewport BEFORE any store
// write so the migration survives the too-much-recursion crash.
//
// NOTE: these are PLAIN FUNCTIONS, not reactive memos — see setBaseSettingsTabLabel.

export function linkedViewport(): ViewportId | null {
  const id = storedLinkedViewport()
  if (!id) return null
  if (getViewportData(id)) return id
  return resolveViewportLink(id, null)
}

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

export function defaultChatViewport(): ViewportId {
  const id = storedDefaultChatViewport()
  if (getViewportData(id)) return id
  return resolveViewportLink(id, "sessions")
}

export function defaultWriteViewport(): ViewportId {
  const id = storedDefaultWriteViewport()
  if (getViewportData(id)) return id
  return resolveViewportLink(id, null)
}
export function defaultLearnitViewport(): ViewportId {
  const id = storedDefaultLearnitViewport()
  if (getViewportData(id)) return id
  return resolveViewportLink(id, "learnit")
}
export function defaultFilesViewport(): ViewportId {
  const id = storedDefaultFilesViewport()
  if (getViewportData(id)) return id
  return resolveViewportLink(id, "files")
}

// Capa 2: when a viewport is replaced (split → leftId, delete → siblingId),
// migrate any stored link that pointed at the dying id to the successor, so
// the link follows the content instead of falling back to the first leaf.
// The memos above then resolve the successor id directly (it already exists
// by the time notifyViewportReplaced fires, post-produce).
onViewportReplaced((oldId, newId) => {
  if (storedLinkedViewport() === oldId) setLinkedViewport(newId)
  if (storedDefaultChatViewport() === oldId) setDefaultChatViewport(newId)
  if (storedDefaultWriteViewport() === oldId) setDefaultWriteViewport(newId)
  if (storedDefaultLearnitViewport() === oldId) setDefaultLearnitViewport(newId)
  if (storedDefaultFilesViewport() === oldId) setDefaultFilesViewport(newId)
})

export type LinkTarget = "viewport" | "chat" | "write" | "learnit" | "files"

let _linkingHandler: ((e: MouseEvent) => void) | null = null

export function beginLinking(target: LinkTarget) {
  if (_linkingHandler) document.removeEventListener("click", _linkingHandler)
  setLinkingMode(true)
  const handler = (e: MouseEvent) => {
    const elem = (e.target as HTMLElement).closest("[data-viewport-id]") as HTMLElement | null
    if (elem) {
      const id = elem.getAttribute("data-viewport-id") as ViewportId
      if (target === "viewport") setLinkedViewport(id)
      else if (target === "chat") setDefaultChatViewport(id)
      else if (target === "write") setDefaultWriteViewport(id)
      else if (target === "learnit") setDefaultLearnitViewport(id)
      else if (target === "files") setDefaultFilesViewport(id)
    }
    setLinkingMode(false)
    if (_linkingHandler) document.removeEventListener("click", _linkingHandler)
    _linkingHandler = null
  }
  _linkingHandler = handler
  document.addEventListener("click", handler)
}

export const [llmProvider, setLLMProvider] =
  createSignal<LLMConfig["llmProvider"]>("deepseek")
export const [llmAgentId, setLLMAgentId] = createSignal("orchestrator")
export const [llmApiKey, setLLMApiKey] = createSignal("")
export const [llmModel, setLLMModel] =
  createSignal<LLMConfig["llmModel"]>("deepseek-v4-pro")
export const [llmReasoning, setLLMReasoning] =
  createSignal<LLMConfig["llmReasoning"]>("max")
export const [agentOverrides, setAgentOverrides] =
  createSignal<Record<string, string>>({})

// ── Default agents (queried from backend /api/agents) + derived memos ──
// Default personas live in the backend (internal/agent/prompts.go); here they
// are only queried to display them and edit via agentOverrides. Hoisted from
// the Settings component so registry sections can consume them directly.
export const [defaultAgents, setDefaultAgents] = createSignal<AgentDef[]>([
  { id: "orchestrator", name: "Orchestrator", systemPrompt: "" },
])

fetch("/api/agents")
  .then((r) => (r.ok ? r.json() : []))
  .then((list: AgentDef[]) => {
    if (Array.isArray(list) && list.length > 0) setDefaultAgents(list)
  })
  .catch(() => {})

export const selectedAgent = createMemo(
  () => defaultAgents().find((a) => a.id === llmAgentId()) ?? defaultAgents()[0],
)

export const isAgentModified = createMemo(() => {
  const agent = selectedAgent()
  const override = agentOverrides()[agent.id]
  return override !== undefined && override !== agent.systemPrompt
})

export const effectivePrompt = createMemo(() => {
  const agent = selectedAgent()
  return agentOverrides()[agent.id] ?? agent.systemPrompt
})

export const agentOptions = createMemo(() =>
  defaultAgents().map((a) => ({
    value: a.id,
    label: llmAgentId() === a.id
      ? `${a.name}${isAgentModified() ? "*" : ""}`
      : a.name,
  })),
)

/** Set the orchestrator system prompt override (or clear it when restoring). */
export function updateAgentPrompt(value: string) {
  const agent = selectedAgent()
  const key = agent.id
  if (value === agent.systemPrompt) {
    setAgentOverrides((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  } else {
    setAgentOverrides((prev) => ({ ...prev, [key]: value }))
  }
  saveConfig()
}

export function resetAgentPrompt() {
  const agent = selectedAgent()
  const key = agent.id
  setAgentOverrides((prev) => {
    const next = { ...prev }
    delete next[key]
    return next
  })
  saveConfig()
}

// ── Subagent configuration (selector + per-subagent overrides) ──
export const [subagentSelector, setSubagentSelector] =
  createSignal("web_researcher")

export function subagentSelectorDefaults(): SubagentConfig {
  const prev = subagentConfig()[subagentSelector()]
  return {
    model: prev?.model || "deepseek-v4-flash",
    reasoning: prev?.reasoning || "high",
    maxSteps: prev?.maxSteps ?? 0,
    maxTokens: prev?.maxTokens ?? 0,
    temperature: prev?.temperature ?? 0,
    topP: prev?.topP ?? 0,
  }
}

export function updateSelectedSubagent(patch: Partial<SubagentConfig>) {
  setSubagentConfig((prev) => ({
    ...prev,
    [subagentSelector()]: { ...subagentSelectorDefaults(), ...patch },
  }))
  saveConfig()
}

export const subagentDefaults = createMemo(() => {
  const map: Record<string, AgentDef> = {}
  for (const a of defaultAgents()) {
    map[a.id] = a
  }
  return map
})

export const isSubagentPromptModified = createMemo(() => {
  const key = subagentSelector()
  const def = subagentDefaults()[key]
  const override = agentOverrides()[key]
  return def && override !== undefined && override !== def.systemPrompt
})

export const subagentOptions = createMemo(() =>
  defaultAgents()
    .filter((a) => a.id !== "orchestrator")
    .map((a) => {
      const modified =
        subagentSelector() === a.id && isSubagentPromptModified()
      return {
        value: a.id,
        label: a.name + (modified ? "*" : ""),
      }
    }),
)

export function subagentPrompt(): string {
  const key = subagentSelector()
  const def = subagentDefaults()[key]
  return agentOverrides()[key] ?? def?.systemPrompt ?? ""
}

export function updateSubagentPrompt(value: string) {
  const key = subagentSelector()
  const def = subagentDefaults()[key]
  if (def && value === def.systemPrompt) {
    setAgentOverrides((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  } else {
    setAgentOverrides((prev) => ({ ...prev, [key]: value }))
  }
  saveConfig()
}

export function resetSubagentPrompt() {
  const key = subagentSelector()
  setAgentOverrides((prev) => {
    const next = { ...prev }
    delete next[key]
    return next
  })
  saveConfig()
}

export const [chatFontSize, setChatFontSize] = createSignal(15)
export const [typewriterSpeed, setTypewriterSpeed] = createSignal(5)
// kept as number; slider uses parseFloat, store/backend use float
export const [tinyfishApiKey, setTinyfishApiKey] = createSignal("")
export const [tinyfishTier, setTinyfishTier] = createSignal("payg")
export const [subagentConfig, setSubagentConfig] = createSignal<
  Record<string, SubagentConfig>
>({})
export const [userName, setUserName] = createSignal("")
export const [userLocation, setUserLocation] = createSignal("")
export const [writeLangs, setWriteLangs] = createSignal<string[]>(["es"])
export const [noteMode, setNoteMode] = createSignal("edit")
export const [noteFontSize, setNoteFontSize] = createSignal(15)
export const [reportFontSize, setReportFontSize] = createSignal(15)
export const [codeFontSize, setCodeFontSize] = createSignal(15)
export const [codeWordWrap, setCodeWordWrap] = createSignal(false)
export const [textFontSize, setTextFontSize] = createSignal(15)
export const [pdfZoom, setPdfZoom] = createSignal(150)
export const [pdfAIFontSize, setPdfAIFontSize] = createSignal(15)
export const [maxTokens, setMaxTokens] = createSignal(0)
export const [temperature, setTemperature] = createSignal(0)
export const [topP, setTopP] = createSignal(0)
export const [maxSteps, setMaxSteps] = createSignal(0)
export const [displayThinking, setDisplayThinking] = createSignal(true)
export const [configLoaded, setConfigLoaded] = createSignal(false)

export const [doclingTableMode, setDoclingTableMode] = createSignal("fast")
export const [doclingImageScale, setDoclingImageScale] = createSignal(1.0)
export const [doclingOcr, setDoclingOcr] = createSignal(true)
export const [doclingCodeEnrich, setDoclingCodeEnrich] = createSignal(false)
export const [doclingFormulaEnrich, setDoclingFormulaEnrich] = createSignal(false)
export const [doclingPictureClassify, setDoclingPictureClassify] = createSignal(false)
export const [doclingForceText, setDoclingForceText] = createSignal(true)
export const [doclingPreset, setDoclingPreset] = createSignal<"fast" | "balanced" | "accurate" | null>("fast")
export const [doclingDirty, setDoclingDirty] = createSignal(false)
export const [doclingRefreshTrigger, setDoclingRefreshTrigger] = createSignal(0)

interface DoclingPresetValues {
  tableMode: string
  imagesScale: number
  doOcr: boolean
  doCodeEnrichment: boolean
  doFormulaEnrichment: boolean
  doPictureClassification: boolean
  forceBackendText: boolean
}

const DOCLING_PRESETS: Record<string, DoclingPresetValues> = {
  fast: {
    tableMode: "fast",
    imagesScale: 1.0,
    doOcr: false,
    doCodeEnrichment: false,
    doFormulaEnrichment: false,
    doPictureClassification: false,
    forceBackendText: true,
  },
  balanced: {
    tableMode: "accurate",
    imagesScale: 1.0,
    doOcr: true,
    doCodeEnrichment: false,
    doFormulaEnrichment: false,
    doPictureClassification: false,
    forceBackendText: false,
  },
  accurate: {
    tableMode: "accurate",
    imagesScale: 2.0,
    doOcr: true,
    doCodeEnrichment: true,
    doFormulaEnrichment: true,
    doPictureClassification: true,
    forceBackendText: false,
  },
}

export function applyDoclingPreset(name: "fast" | "balanced" | "accurate") {
  const p = DOCLING_PRESETS[name]
  setDoclingTableMode(p.tableMode)
  setDoclingImageScale(p.imagesScale)
  setDoclingOcr(p.doOcr)
  setDoclingCodeEnrich(p.doCodeEnrichment)
  setDoclingFormulaEnrich(p.doFormulaEnrichment)
  setDoclingPictureClassify(p.doPictureClassification)
  setDoclingForceText(p.forceBackendText)
  setDoclingPreset(name)
  setDoclingDirty(true)
  saveConfig()
}

export const [sessionProvider, setSessionProvider] = createSignal("")
export const [sessionModel, setSessionModel] = createSignal("")
export const [sessionReasoning, setSessionReasoning] = createSignal("")
export const [sessionAgentId, setSessionAgentId] = createSignal("")
export const [sessionSkillId, setSessionSkillId] = createSignal("")

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

/** Resolved token-cost context for the active session, or null when there is
 *  no usage yet or no price table for the active model. Placed here (after
 *  llmModel's declaration) because createMemo runs its factory eagerly on
 *  creation — referencing llmModel above its const would hit the TDZ. */
export const usageInfo = createMemo(() => {
  const usage = sessionUsage()
  const model = llmModel()
  if (!usage || !model) return null
  const prices = PRICES[model]
  if (!prices) return null
  return { usage, prices, model }
})

export async function loadSessionConfig(sessionId: string) {
  const res = await fetch(`/api/sessions/${sessionId}/config`)
  if (!res.ok) return
  const cfg: SessionConfig = await res.json()
  if (cfg.provider) setSessionProvider(cfg.provider)
  if (cfg.model) setSessionModel(cfg.model)
  if (cfg.reasoning) setSessionReasoning(cfg.reasoning)
  if (cfg.agentId) setSessionAgentId(cfg.agentId)
  if (cfg.skillId) setSessionSkillId(cfg.skillId)
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
      skillId: sessionSkillId(),
    }),
  }).catch((err) => console.error("save session config:", err))
}

export async function saveSessionConfigAsync(sessionId: string): Promise<void> {
  await fetch(`/api/sessions/${sessionId}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: sessionProvider(),
      model: sessionModel(),
      reasoning: sessionReasoning(),
      agentId: sessionAgentId(),
      skillId: sessionSkillId(),
    }),
  })
}

let saveTimer: ReturnType<typeof setTimeout> | null = null

export async function loadConfig() {
  const res = await fetch("/api/config")
  if (res.ok) {
    const cfg: LLMConfig = await res.json()
    if (cfg.llmProvider) setLLMProvider(cfg.llmProvider)
    if (cfg.llmAgentId) setLLMAgentId(cfg.llmAgentId)
    setLLMApiKey(cfg.llmApiKey || "")
    if (cfg.llmModel) setLLMModel(cfg.llmModel)
    if (cfg.llmReasoning) setLLMReasoning(cfg.llmReasoning)
    if (cfg.agentOverrides) setAgentOverrides(cfg.agentOverrides)
    if (cfg.chatFontSize) setChatFontSize(cfg.chatFontSize)
    if (cfg.typewriterSpeed) setTypewriterSpeed(cfg.typewriterSpeed)
    setTinyfishApiKey(cfg.tinyfishApiKey || "")
    if (cfg.tinyfishTier) setTinyfishTier(cfg.tinyfishTier)
    if (cfg.subagentConfig) setSubagentConfig(cfg.subagentConfig)
    if (cfg.userName) setUserName(cfg.userName)
    if (cfg.userLocation) setUserLocation(cfg.userLocation)
    if (cfg.defaultLearnitViewport) setDefaultLearnitViewport(cfg.defaultLearnitViewport)
    if (cfg.defaultFilesViewport) setDefaultFilesViewport(cfg.defaultFilesViewport)
    if (cfg.writeLangs) setWriteLangs(cfg.writeLangs)
    if (cfg.noteMode) setNoteMode(cfg.noteMode)
    if (cfg.noteFontSize) setNoteFontSize(cfg.noteFontSize)
    if (cfg.reportFontSize) setReportFontSize(cfg.reportFontSize)
    if (cfg.codeFontSize) setCodeFontSize(cfg.codeFontSize)
    if (cfg.codeWordWrap !== undefined) setCodeWordWrap(cfg.codeWordWrap)
    if (cfg.textFontSize) setTextFontSize(cfg.textFontSize)
    if (cfg.pdfZoom) setPdfZoom(cfg.pdfZoom)
    if (cfg.pdfAIFontSize) setPdfAIFontSize(cfg.pdfAIFontSize)
    if (cfg.maxTokens) setMaxTokens(cfg.maxTokens)
    if (cfg.temperature) setTemperature(cfg.temperature)
    if (cfg.topP) setTopP(cfg.topP)
    if (cfg.maxSteps) setMaxSteps(cfg.maxSteps)
    if (cfg.displayThinking !== undefined) setDisplayThinking(cfg.displayThinking)
    if (cfg.doclingConfig) {
      const dc = cfg.doclingConfig
      if (dc.tableMode) setDoclingTableMode(dc.tableMode)
      if (dc.imagesScale !== undefined) setDoclingImageScale(dc.imagesScale)
      if (dc.doOcr !== undefined) setDoclingOcr(dc.doOcr)
      if (dc.doCodeEnrichment !== undefined) setDoclingCodeEnrich(dc.doCodeEnrichment)
      if (dc.doFormulaEnrichment !== undefined) setDoclingFormulaEnrich(dc.doFormulaEnrichment)
      if (dc.doPictureClassification !== undefined) setDoclingPictureClassify(dc.doPictureClassification)
      if (dc.forceBackendText !== undefined) setDoclingForceText(dc.forceBackendText)
    }
  }
  setConfigLoaded(true)
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
          typewriterSpeed: typewriterSpeed(),
          tinyfishApiKey: tinyfishApiKey(),
          tinyfishTier: tinyfishTier(),
          subagentConfig: subagentConfig(),
          userName: userName(),
          userLocation: userLocation(),
          defaultLearnitViewport: storedDefaultLearnitViewport(),
          defaultFilesViewport: storedDefaultFilesViewport(),
          writeLangs: writeLangs(),
          noteMode: noteMode(),
          noteFontSize: noteFontSize(),
          reportFontSize: reportFontSize(),
          codeFontSize: codeFontSize(),
          codeWordWrap: codeWordWrap(),
          textFontSize: textFontSize(),
          pdfZoom: pdfZoom(),
          pdfAIFontSize: pdfAIFontSize(),
          maxTokens: maxTokens(),
          temperature: temperature(),
          topP: topP(),
          maxSteps: maxSteps(),
          displayThinking: displayThinking(),
          doclingConfig: {
            tableMode: doclingTableMode(),
            imagesScale: doclingImageScale(),
            doOcr: doclingOcr(),
            doCodeEnrichment: doclingCodeEnrich(),
            doFormulaEnrichment: doclingFormulaEnrich(),
            doPictureClassification: doclingPictureClassify(),
            forceBackendText: doclingForceText(),
          },
        }),
      })
    } catch (err) {
      console.error("save config:", err)
    }
  }, 500)
}

export function confirmLinkViewport(vpId: ViewportId) {
  const el = document.querySelector(`[data-viewport-id="${vpId}"]`)
  if (el) el.dispatchEvent(new MouseEvent("click", { bubbles: true }))
}

export function cancelLinking() {
  document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }))
}
