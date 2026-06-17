import { createSignal, createMemo } from "solid-js"
import type { ViewportId } from "../tabs"
import type { LLMConfig, SessionConfig, SubagentConfig } from "../types"
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
export const [defaultFilesViewport, setDefaultFilesViewport] =
  createSignal<ViewportId>("1100")

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
export const [maxTokens, setMaxTokens] = createSignal(0)
export const [temperature, setTemperature] = createSignal(0)
export const [topP, setTopP] = createSignal(0)
export const [maxSteps, setMaxSteps] = createSignal(0)
export const [displayThinking, setDisplayThinking] = createSignal(true)

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
    if (cfg.typewriterSpeed) setTypewriterSpeed(cfg.typewriterSpeed)
    if (cfg.tinyfishApiKey) setTinyfishApiKey(cfg.tinyfishApiKey)
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
          defaultLearnitViewport: defaultLearnitViewport(),
          defaultFilesViewport: defaultFilesViewport(),
          writeLangs: writeLangs(),
          noteMode: noteMode(),
          noteFontSize: noteFontSize(),
          reportFontSize: reportFontSize(),
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
