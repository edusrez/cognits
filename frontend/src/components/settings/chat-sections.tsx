/** Chat-linked Settings sections — Info, Agent, Subagents, Shared Data.
 *  All match ctx.tabId === "chat" with a linked viewport. They read reactive
 *  state directly from the stores (settings-store / chat-store / session-store)
 *  so they update fine-grained without re-running render(). */

import { Show } from "solid-js"
import { createSignal } from "solid-js"
import { registerSection } from "../../lib/settings-sections"
import SliderField from "../SliderField"
import Dropdown from "../Dropdown"
import CollapsibleSection from "../CollapsibleSection"
import { activeSessionId } from "../../stores/session-store"
import { conversationStarted } from "../../stores/chat-store"
import { isSetupActive } from "../../stores/setup-store"
import {
  usageInfo, formatCost, formatNumber,
  activeProvider, setLLMProvider, setSessionProvider, saveSessionConfig,
  llmApiKey, setLLMApiKey,
  activeModel, setLLMModel, setSessionModel,
  activeReasoning, setLLMReasoning, setSessionReasoning,
  activeAgentId, setLLMAgentId, setSessionAgentId,
  agentOptions, isAgentModified, effectivePrompt, updateAgentPrompt, resetAgentPrompt,
  maxTokens, setMaxTokens, temperature, setTemperature, topP, setTopP,
  maxSteps, setMaxSteps,
  subagentSelector, setSubagentSelector, subagentOptions, subagentConfig,
  updateSelectedSubagent,
  tinyfishApiKey, setTinyfishApiKey, tinyfishTier, setTinyfishTier,
  isSubagentPromptModified, subagentPrompt, updateSubagentPrompt, resetSubagentPrompt,
  userName, setUserName, userLocation, setUserLocation,
  saveConfig,
} from "../../stores/settings-store"

const chatMatch = (ctx: { linkedViewport: boolean; tabId: string | null }) =>
  ctx.linkedViewport && ctx.tabId === "chat" && !isSetupActive()

// ── Info: token-cost breakdown for the active session ──

registerSection({
  id: "chat:info",
  matches: chatMatch,
  render: () => (
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
  ),
})

// ── Agent: orchestrator provider/model/prompt for the active session ──
// showKey (password visibility) is UI-pure state local to this section.

registerSection({
  id: "chat:agent",
  matches: chatMatch,
  render: () => {
    const [showKey, setShowKey] = createSignal(false)
    return (
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
                onInput={(e) => { setLLMApiKey(e.currentTarget.value); saveConfig() }}
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
                  onClick={resetAgentPrompt}
                  title="Restore default prompt"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="23 4 23 10 17 10" />
                    <path d="M20.49 15a9 9 011-2.12-9.36L23 10" />
                  </svg>
                </button>
              </Show>
            </div>
            <textarea
              value={effectivePrompt()}
              onInput={(e) => updateAgentPrompt(e.currentTarget.value)}
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
    )
  },
})

// ── Subagents: per-subagent provider/model/prompt overrides ──

registerSection({
  id: "chat:subagents",
  matches: chatMatch,
  render: () => (
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
                  <path d="M20.49 15a9 9 011-2.12-9.36L23 10" />
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
  ),
})

// ── Shared Data: user name + location shared with the agent ──

registerSection({
  id: "chat:shared-data",
  matches: chatMatch,
  render: () => (
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
  ),
})
