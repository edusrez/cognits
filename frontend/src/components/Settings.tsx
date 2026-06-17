import { Show, For, createMemo, createSignal, createEffect, onCleanup } from "solid-js"
import {
  linkingMode,
  beginLinking,
  linkedViewport,
  setLinkedViewport,
  hiddenBasicTabs,
  toggleBasicTab,
  defaultChatViewport,
  setDefaultChatViewport,
  defaultWriteViewport,
  setDefaultWriteViewport,
  llmProvider,
  setLLMProvider,
  llmAgentId,
  setLLMAgentId,
  llmApiKey,
  setLLMApiKey,
  llmModel,
  setLLMModel,
  llmReasoning,
  setLLMReasoning,
  agentOverrides,
  setAgentOverrides,
  chatFontSize,
  setChatFontSize,
  typewriterSpeed,
  setTypewriterSpeed,
  tinyfishApiKey,
  setTinyfishApiKey,
  tinyfishTier,
  setTinyfishTier,
  subagentConfig,
  setSubagentConfig,
  userName,
  setUserName,
  userLocation,
  setUserLocation,
  activeProvider,
  activeModel,
  activeReasoning,
  activeAgentId,
  sessionProvider,
  setSessionProvider,
  sessionModel,
  setSessionModel,
  sessionReasoning,
  setSessionReasoning,
  sessionAgentId,
  setSessionAgentId,
  loadSessionConfig,
  saveSessionConfig,
  defaultLearnitViewport,
  setDefaultLearnitViewport,
  defaultFilesViewport,
  setDefaultFilesViewport,
  doclingTableMode,
  setDoclingTableMode,
  doclingImageScale,
  setDoclingImageScale,
  doclingOcr,
  setDoclingOcr,
  doclingCodeEnrich,
  setDoclingCodeEnrich,
  doclingFormulaEnrich,
  setDoclingFormulaEnrich,
  doclingPictureClassify,
  setDoclingPictureClassify,
  doclingForceText,
  setDoclingForceText,
  doclingPreset,
  setDoclingPreset,
  applyDoclingPreset,
  doclingDirty,
  setDoclingDirty,
  doclingRefreshTrigger,
  setDoclingRefreshTrigger,
  writeLangs,
  setWriteLangs,
  noteMode,
  setNoteMode,
  noteFontSize,
  setNoteFontSize,
  reportFontSize,
  setReportFontSize,
  codeFontSize,
  setCodeFontSize,
  textFontSize,
  setTextFontSize,
  pdfZoom,
  setPdfZoom,
  pdfAIFontSize,
  setPdfAIFontSize,
  maxTokens,
  setMaxTokens,
  temperature,
  setTemperature,
  topP,
  setTopP,
  maxSteps,
  setMaxSteps,
  displayThinking,
  setDisplayThinking,
  saveConfig,
} from "../stores/settings-store"
import { getViewportData, resetTree, setTabLabel } from "../stores/viewport-tree-store"
import { currentMessages, sessionUsage } from "../stores/chat-store"
import { activeSessionId } from "../stores/session-store"
import type { ViewportId } from "../tabs"
import type { AgentDef, ChatUsage, SubagentConfig } from "../types"
import Dropdown from "./Dropdown"
import CollapsibleSection from "./CollapsibleSection"
import SliderField from "./SliderField"

const PRICES: Record<string, { inputCacheHit: number; inputCacheMiss: number; output: number }> = {
  "deepseek-v4-flash": { inputCacheHit: 0.0028, inputCacheMiss: 0.14, output: 0.28 },
  "deepseek-v4-pro": { inputCacheHit: 0.003625, inputCacheMiss: 0.435, output: 0.87 },
}

function formatCost(tokens: number, pricePerM: number): string {
  return "$" + ((tokens / 1_000_000) * pricePerM).toFixed(2)
}

function formatNumber(n: number): string {
  return n.toLocaleString()
}

function tabDisplayName(tabId: string | null): string | null {
  if (!tabId) return null
  if (tabId.startsWith("note:")) return "Note"
  if (tabId.startsWith("report:")) return "Web Report"
  const names: Record<string, string> = {
    chat: "Chat",
    sessions: "Sessions",
    write: "Write",
    learnit: ".cognits",
  }
  return names[tabId] ?? null
}

// Default agents live in the backend (internal/agent/prompts.go);
// here they're only queried to display them and edit via agentOverrides.
const [defaultAgents, setDefaultAgents] = createSignal<AgentDef[]>([
  { id: "orchestrator", name: "Orchestrator", systemPrompt: "" },
])

fetch("/api/agents")
  .then((r) => (r.ok ? r.json() : []))
  .then((list: AgentDef[]) => {
    if (Array.isArray(list) && list.length > 0) setDefaultAgents(list)
  })
  .catch(() => {})

import "./settings/sections" // auto-registers sections via side-effect
import type { LinkTarget } from "../stores/settings-store"
import { getMatchingSections } from "../lib/settings-sections"

const basicTabs = [
  { id: "files", label: "Files" },
  { id: "sessions", label: "Sessions" },
] as const

export default function Settings(props: { viewportId?: ViewportId; tabId?: string }) {
  const scopedTabId = createMemo(() => {
    const t = props.tabId || ""
    return t.startsWith("settings:") ? t.slice(9) : null
  })

  const linkedActiveTabId = createMemo(() => {
    if (scopedTabId()) return scopedTabId()
    const vp = linkedViewport()
    if (!vp) return null
    return getViewportData(vp)?.activeTabId ?? null
  })

  const pdfPath = createMemo(() => {
    const tabId = linkedActiveTabId()
    if (tabId && tabId.startsWith("pdf:")) return tabId.slice(4)
    return null
  })

  const sections = createMemo(() =>
    getMatchingSections({
      linkedViewport: !!linkedViewport(),
      tabId: linkedActiveTabId(),
    })
  )

  const conversationStarted = createMemo(() => currentMessages().length > 0)

  const usageInfo = createMemo(() => {
    const usage = sessionUsage()
    const model = llmModel()
    if (!usage || !model) return null
    const prices = PRICES[model]
    if (!prices) return null
    return { usage, prices, model }
  })

  const selectedAgent = createMemo(() => {
    return defaultAgents().find((a) => a.id === llmAgentId()) ?? defaultAgents()[0]
  })

  const isAgentModified = createMemo(() => {
    const agent = selectedAgent()
    const override = agentOverrides()[agent.id]
    return override !== undefined && override !== agent.systemPrompt
  })

  const effectivePrompt = createMemo(() => {
    const agent = selectedAgent()
    return agentOverrides()[agent.id] ?? agent.systemPrompt
  })

  const agentOptions = createMemo(() =>
    defaultAgents().map((a) => ({
      value: a.id,
      label: llmAgentId() === a.id
        ? `${a.name}${isAgentModified() ? "*" : ""}`
        : a.name,
    })))

  const [showKey, setShowKey] = createSignal(false)

  const [subagentSelector, setSubagentSelector] = createSignal("web_researcher")

  function subagentSelectorDefaults(): SubagentConfig {
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

  function updateSelectedSubagent(patch: Partial<SubagentConfig>) {
    setSubagentConfig((prev) => ({
      ...prev,
      [subagentSelector()]: { ...subagentSelectorDefaults(), ...patch },
    }))
    saveConfig()
  }

  const subagentDefaults = createMemo(() => {
    const map: Record<string, AgentDef> = {}
    for (const a of defaultAgents()) {
      map[a.id] = a
    }
    return map
  })

  const isSubagentPromptModified = createMemo(() => {
    const key = subagentSelector()
    const def = subagentDefaults()[key]
    const override = agentOverrides()[key]
    return def && override !== undefined && override !== def.systemPrompt
  })

  const subagentOptions = createMemo(() =>
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

  function subagentPrompt(): string {
    const key = subagentSelector()
    const def = subagentDefaults()[key]
    return agentOverrides()[key] ?? def?.systemPrompt ?? ""
  }

  function updateSubagentPrompt(value: string) {
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

  function resetSubagentPrompt() {
    const key = subagentSelector()
    setAgentOverrides((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    saveConfig()
  }

  const setAndSaveKey = (v: string) => {
    setLLMApiKey(v)
    saveConfig()
  }

  createEffect(() => {
    const vpId = props.viewportId
    const tabId = linkedActiveTabId()
    if (!vpId) return
    const tabLabel = tabDisplayName(tabId)
    const label = tabLabel ? `Settings (${tabLabel})` : "Settings"
    setTabLabel(vpId, "settings", label)
  })

  const updatePrompt = (value: string) => {
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

  const resetPrompt = () => {
    const agent = selectedAgent()
    const key = agent.id
    setAgentOverrides((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    saveConfig()
  }

  return (
    <div class="p-3 flex flex-col gap-3 text-[13px]">
      <Show when={!linkedViewport() && !scopedTabId()}>
        <p class="text-[#9a9a9a] leading-relaxed">
          Settings works linked to a viewport to show the specific
          settings for that viewport's active tab.
        </p>
        <div class="flex justify-center">
          <button
            class="border border-white/20 px-3 py-1.5 hover:bg-white/10 transition-colors cursor-pointer w-full"
            onClick={() => beginLinking("viewport")}
          >
            Link Viewport
          </button>
        </div>
      </Show>

      <Show when={linkingMode()}>
        <p class="text-[#9a9a9a]">Click on a viewport to link it.</p>
      </Show>

      {/* ── Registry-driven sections ── */}
      <For each={sections()}>
        {(section) => section.render()}
      </For>

      {/* ── PDF AI Vision (needs component-level pdfPath) ── */}
      <Show when={linkedViewport() && (scopedTabId()?.startsWith("pdf:") || linkedActiveTabId()?.startsWith("pdf:"))}>
        <CollapsibleSection title="AI Vision">
          <div class="flex flex-col gap-2">

            <div class="flex items-center justify-between gap-2">
              <label class="text-[#9a9a9a]">Quality preset</label>
            </div>
            <Dropdown
              value={doclingPreset() ?? "fast"}
              options={[
                { value: "fast", label: "Fast" },
                { value: "balanced", label: "Balanced" },
                { value: "accurate", label: "Accurate" },
              ]}
              onChange={(v) => applyDoclingPreset(v as "fast" | "balanced" | "accurate")}
            />

            <div class="flex items-center justify-between gap-2">
              <label class="text-[#9a9a9a] text-[13px]">Table accuracy</label>
            </div>
            <Dropdown
              value={doclingTableMode()}
              options={[
                { value: "fast", label: "Fast" },
                { value: "accurate", label: "Accurate" },
              ]}
              onChange={(v) => {
                setDoclingTableMode(v)
                setDoclingPreset(null)
                setDoclingDirty(true)
                saveConfig()
              }}
            />

            <For each={[
              ["OCR", doclingOcr, setDoclingOcr] as const,
              ["Code enrichment", doclingCodeEnrich, setDoclingCodeEnrich] as const,
              ["Formula enrichment", doclingFormulaEnrich, setDoclingFormulaEnrich] as const,
              ["Picture classification", doclingPictureClassify, setDoclingPictureClassify] as const,
              ["Force PDF text", doclingForceText, setDoclingForceText] as const,
            ]}>
              {([label, signal, setter]) => (
                <div>
                  <div class="flex items-center justify-between gap-2">
                    <label class="text-[#9a9a9a] text-[13px]">{label}</label>
                  </div>
                  <Dropdown
                    value={signal() ? "on" : "off"}
                    options={[
                      { value: "on", label: "On" },
                      { value: "off", label: "Off" },
                    ]}
                    onChange={(v) => {
                      setter(v === "on")
                      setDoclingPreset(null)
                      setDoclingDirty(true)
                      saveConfig()
                    }}
                  />
                </div>
              )}
            </For>

            <SliderField
              label="Image resolution"
              value={doclingImageScale()}
              onInput={(v) => {
                setDoclingImageScale(v)
                setDoclingPreset(null)
                setDoclingDirty(true)
                saveConfig()
              }}
              min={1.0}
              max={2.0}
              step={0.1}
              formatValue={(v) => v.toFixed(1) + "x"}
            />

            <Show when={doclingDirty() && pdfPath()}>
              <div class="border-t border-white/5 pt-2 mt-1">
                <p class="text-[10px] text-[#5a5a5a] mb-1">
                  The PDF will be re-converted with these settings.
                </p>
                <button
                  class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors cursor-pointer w-full"
                  onClick={() => {
                    setDoclingRefreshTrigger((t) => t + 1)
                    setDoclingDirty(false)
                  }}
                >
                  Apply &amp; Re-render this PDF
                </button>
              </div>
            </Show>
          </div>
        </CollapsibleSection>
      </Show>

      <Show when={linkedViewport() && linkedActiveTabId() === "chat"}>
        <CollapsibleSection title="Info">
          <div class="flex flex-col gap-1">
            <Show
              when={usageInfo()}
              fallback={
                <span class="text-[#6a6a6a]">
                  Send a message to see token statistics.
                </span>
              }
            >
              {(info) => (
                <>
                  <div class="flex justify-between text-[13px]">
                    <span class="text-[#9a9a9a]">Input Cache Miss</span>
                    <span>
                      {formatNumber(info().usage.prompt_cache_miss_tokens)} ({formatCost(info().usage.prompt_cache_miss_tokens, info().prices.inputCacheMiss)})
                    </span>
                  </div>
                  <div class="flex justify-between text-[13px]">
                    <span class="text-[#9a9a9a]">Input Cache Hit</span>
                    <span>
                      {formatNumber(info().usage.prompt_cache_hit_tokens)} ({formatCost(info().usage.prompt_cache_hit_tokens, info().prices.inputCacheHit)})
                    </span>
                  </div>
                  <div class="flex justify-between text-[13px]">
                    <span class="text-[#9a9a9a]">Output</span>
                    <span>
                      {formatNumber(info().usage.completion_tokens)} ({formatCost(info().usage.completion_tokens, info().prices.output)})
                    </span>
                  </div>
                </>
              )}
            </Show>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title="Agent">
          <div class="flex flex-col gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Provider</label>
              <Dropdown
                value={activeProvider()}
                options={[
                  { value: "deepseek" as const, label: "DeepSeek" },
                ]}
                onChange={(v) => {
                  const sid = activeSessionId()
                  if (sid) { setSessionProvider(v); saveSessionConfig(sid) }
                  else { setLLMProvider(v as "deepseek"); saveConfig() }
                }}
                disabled={conversationStarted()}
              />
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">API Key</label>
              <div class="flex gap-1">
                <input
                  type={showKey() ? "text" : "password"}
                  value={llmApiKey()}
                  onInput={(e) => setAndSaveKey(e.currentTarget.value)}
                  class="flex-1 bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40 disabled:opacity-40 disabled:cursor-not-allowed"
                  placeholder="sk-..."
                  disabled={conversationStarted()}
                />
                <button
                  class="border border-white/20 px-2 py-1 hover:bg-white/10 cursor-pointer shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                  onClick={() => setShowKey((p) => !p)}
                  disabled={conversationStarted()}
                  title={showKey() ? "Hide" : "Show"}
                >
                  {showKey() ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                      <circle cx="12" cy="12" r="3"/>
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/>
                      <line x1="1" y1="1" x2="23" y2="23"/>
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Model</label>
              <Dropdown
                value={activeModel() as "deepseek-v4-flash" | "deepseek-v4-pro"}
                options={[
                  { value: "deepseek-v4-flash" as const, label: "V4 Flash" },
                  { value: "deepseek-v4-pro" as const, label: "V4 Pro" },
                ]}
                onChange={(v) => {
                  const sid = activeSessionId()
                  if (sid) { setSessionModel(v); saveSessionConfig(sid) }
                  else { setLLMModel(v); saveConfig() }
                }}
                disabled={conversationStarted()}
              />
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Reasoning</label>
              <Dropdown
                value={activeReasoning() as "disabled" | "high" | "max"}
                options={[
                  { value: "disabled" as const, label: "Disabled" },
                  { value: "high" as const, label: "High" },
                  { value: "max" as const, label: "Maximum" },
                ]}
                onChange={(v) => {
                  const sid = activeSessionId()
                  if (sid) { setSessionReasoning(v); saveSessionConfig(sid) }
                  else { setLLMReasoning(v); saveConfig() }
                }}
                disabled={conversationStarted()}
              />
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Agent</label>
              <Dropdown
                value={activeAgentId()}
                options={agentOptions()}
                onChange={(v) => {
                  const sid = activeSessionId()
                  if (sid) { setSessionAgentId(v); saveSessionConfig(sid) }
                  else { setLLMAgentId(v); saveConfig() }
                }}
                disabled={conversationStarted()}
              />
            </div>

            <div class="flex flex-col gap-1">
              <div class="flex items-center justify-between">
                <label class="text-[#9a9a9a]">System Prompt</label>
                <Show when={isAgentModified() && !conversationStarted()}>
                  <button
                    class="text-[#6a6a6a] hover:text-[#e0e0e0] transition-colors cursor-pointer"
                    onClick={resetPrompt}
                    title="Restore default prompt"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="23 4 23 10 17 10" />
                      <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10" />
                    </svg>
                  </button>
                </Show>
              </div>
              <textarea
                value={effectivePrompt()}
                onInput={(e) => updatePrompt(e.currentTarget.value)}
                class="bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40 resize-none h-36 disabled:opacity-40 disabled:cursor-not-allowed"
                readOnly={conversationStarted()}
                disabled={conversationStarted()}
              />
            </div>

            <SliderField
              label="Max Output Tokens"
              value={maxTokens() || 4096}
              onInput={(v) => { setMaxTokens(v); saveConfig() }}
              min={256}
              max={384000}
              step={256}
              disabled={conversationStarted()}
            />

            <SliderField
              label="Temperature"
              value={temperature() || 1.0}
              onInput={(v) => { setTemperature(v); saveConfig() }}
              min={0}
              max={2}
              step={0.05}
              disabled={conversationStarted() || activeReasoning() !== "disabled"}
              disabledHint="No effect in thinking mode"
            />

            <SliderField
              label="Top P"
              value={topP() || 1.0}
              onInput={(v) => { setTopP(v); saveConfig() }}
              min={0}
              max={1}
              step={0.05}
              disabled={conversationStarted() || activeReasoning() !== "disabled"}
              disabledHint="No effect in thinking mode"
            />

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Max Steps</label>
              <div class="text-[11px] text-[#6a6a6a]">0 = default (999)</div>
              <input
                type="number"
                min="0"
                max="100"
                value={maxSteps() || 0}
                onInput={(e) => { setMaxSteps(parseInt(e.currentTarget.value) || 0); saveConfig() }}
                class="no-spinner bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40 w-20 disabled:opacity-40 disabled:cursor-not-allowed"
                disabled={conversationStarted()}
              />
            </div>

          </div>
        </CollapsibleSection>

        <CollapsibleSection title="Subagents">
          <div class="flex flex-col gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Subagent</label>
              <Dropdown
                value={subagentSelector()}
                options={subagentOptions()}
                onChange={(v) => setSubagentSelector(v)}
                disabled={conversationStarted()}
              />
            </div>

            <Show when={subagentSelector() === "web_researcher"}>
            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Service Provider</label>
              <Dropdown
                value={"tinyfish" as const}
                options={[
                  { value: "tinyfish" as const, label: "TinyFish" },
                ]}
                onChange={() => {}}
                disabled={true}
              />
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">API Key</label>
              <div class="flex gap-1">
                <input
                  type="password"
                  value={tinyfishApiKey()}
                  onInput={(e) => {
                    setTinyfishApiKey(e.currentTarget.value)
                    saveConfig()
                  }}
                  class="flex-1 bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40 disabled:opacity-40 disabled:cursor-not-allowed"
                  placeholder="sk-tinyfish-..."
                  disabled={conversationStarted()}
                />
              </div>
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Tier</label>
              <Dropdown
                value={tinyfishTier() as string}
                options={[
                  { value: "gratuito" as const, label: "Free" },
                  { value: "payg" as const, label: "PAYG" },
                  { value: "starter" as const, label: "Starter" },
                  { value: "pro" as const, label: "Pro" },
                ]}
                onChange={(v) => {
                  setTinyfishTier(v)
                  saveConfig()
                }}
                disabled={conversationStarted()}
              />
            </div>
            </Show>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">AI Provider</label>
              <Dropdown
                value={"deepseek" as const}
                options={[
                  { value: "deepseek" as const, label: "DeepSeek" },
                ]}
                onChange={() => {}}
                disabled={true}
              />
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Model</label>
              <Dropdown
                value={(subagentConfig()[subagentSelector()]?.model || "deepseek-v4-flash") as "deepseek-v4-flash" | "deepseek-v4-pro"}
                options={[
                  { value: "deepseek-v4-flash" as const, label: "V4 Flash" },
                  { value: "deepseek-v4-pro" as const, label: "V4 Pro" },
                ]}
                onChange={(v) => updateSelectedSubagent({ model: v })}
                disabled={conversationStarted()}
              />
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Reasoning</label>
              <Dropdown
                value={(subagentConfig()[subagentSelector()]?.reasoning || "high") as "disabled" | "high" | "max"}
                options={[
                  { value: "disabled" as const, label: "Disabled" },
                  { value: "high" as const, label: "High" },
                  { value: "max" as const, label: "Maximum" },
                ]}
                onChange={(v) => updateSelectedSubagent({ reasoning: v })}
                disabled={conversationStarted()}
              />
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Max Steps</label>
              <div class="flex items-center gap-2">
                <input
                  type="number"
                  min="0"
                   max="200"
                  value={subagentConfig()[subagentSelector()]?.maxSteps ?? 0}
                  onInput={(e) => {
                    updateSelectedSubagent({ maxSteps: parseInt(e.currentTarget.value) || 0 })
                  }}
                  class="no-spinner bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40 w-20 disabled:opacity-40 disabled:cursor-not-allowed"
                  disabled={conversationStarted()}
                />
                <span class="text-[#6a6a6a] text-[13px]">(0 = default: 100)</span>
              </div>
            </div>

            <SliderField
              label="Max Output Tokens"
              value={subagentConfig()[subagentSelector()]?.maxTokens || 4096}
              onInput={(v) => updateSelectedSubagent({ maxTokens: v })}
              min={256}
              max={384000}
              step={256}
              disabled={conversationStarted()}
            />

            <SliderField
              label="Temperature"
              value={subagentConfig()[subagentSelector()]?.temperature || 1.0}
              onInput={(v) => updateSelectedSubagent({ temperature: v })}
              min={0}
              max={2}
              step={0.05}
              disabled={conversationStarted() || subagentConfig()[subagentSelector()]?.reasoning !== "disabled"}
              disabledHint="No effect in thinking mode"
            />

            <SliderField
              label="Top P"
              value={subagentConfig()[subagentSelector()]?.topP || 1.0}
              onInput={(v) => updateSelectedSubagent({ topP: v })}
              min={0}
              max={1}
              step={0.05}
              disabled={conversationStarted() || subagentConfig()[subagentSelector()]?.reasoning !== "disabled"}
              disabledHint="No effect in thinking mode"
            />

            <div class="flex flex-col gap-1 mt-1">
              <div class="flex items-center justify-between">
                <label class="text-[#9a9a9a]">System Prompt</label>
                <Show when={isSubagentPromptModified() && !conversationStarted()}>
                  <button
                    class="text-[#6a6a6a] hover:text-[#e0e0e0] transition-colors cursor-pointer"
                    onClick={resetSubagentPrompt}
                    title="Restore default prompt"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="23 4 23 10 17 10" />
                      <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10" />
                    </svg>
                  </button>
                </Show>
              </div>
              <textarea
                value={subagentPrompt()}
                onInput={(e) => updateSubagentPrompt(e.currentTarget.value)}
                class="bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40 resize-none h-36 disabled:opacity-40 disabled:cursor-not-allowed"
                readOnly={conversationStarted()}
                disabled={conversationStarted()}
              />
            </div>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title="Shared Data">
          <div class="flex flex-col gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Your Name</label>
              <input
                type="text"
                value={userName()}
                onInput={(e) => {
                  setUserName(e.currentTarget.value)
                  saveConfig()
                }}
                class="bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40"
                placeholder="Eduardo"
              />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[#9a9a9a]">Location</label>
              <input
                type="text"
                value={userLocation()}
                onInput={(e) => {
                  setUserLocation(e.currentTarget.value)
                  saveConfig()
                }}
                class="bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40"
                placeholder="Madrid, España"
              />
            </div>
          </div>
        </CollapsibleSection>

      </Show>

      <CollapsibleSection title="General Settings">
        <div class="flex flex-col gap-2">
          <div class="text-[#9a9a9a]">Basic tabs</div>
          <For each={basicTabs}>
            {(tab) => {
              const hidden = () => hiddenBasicTabs().has(tab.id)
              return (
                <button
                  class="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-white/10 transition-colors cursor-pointer"
                  onClick={() => toggleBasicTab(tab.id)}
                >
                  <span
                    class="inline-block w-3.5 h-3.5 border border-white/30 shrink-0"
                    classList={{ "bg-white/20": !hidden() }}
                  />
                  <span class={hidden() ? "text-[#6a6a6a]" : ""}>
                    {tab.label}
                  </span>
                </button>
              )
            }}
          </For>

          <div class="mt-1">
            <button
              class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors cursor-pointer w-full text-center"
              onClick={resetTree}
            >
              Restore Default Layout
            </button>
          </div>

          <Show when={linkedViewport() && !scopedTabId()}>
            <div class="flex flex-col items-center gap-2 mt-2">
              <button
                class="border border-white/20 px-3 py-1.5 hover:bg-white/10 transition-colors cursor-pointer w-full"
                onClick={() => beginLinking("viewport")}
                disabled={linkingMode()}
              >
                Change Linked Viewport
              </button>
            </div>
          </Show>
        </div>
      </CollapsibleSection>
    </div>
  )
}
