/** API Keys Settings section — shown when linked to or scoped for "apikeys". */

import { createSignal } from "solid-js"
import { registerSection, type SectionContext } from "../../lib/settings-sections"
import Dropdown from "../Dropdown"
import CollapsibleSection from "../CollapsibleSection"
import {
  activeProvider, setLLMProvider,
  llmApiKey, setLLMApiKey,
  tinyfishApiKey, setTinyfishApiKey,
  saveConfig,
} from "../../stores/settings-store"

const apikeysMatch = (ctx: SectionContext) =>
  ctx.scoped && ctx.tabId === "apikeys"

registerSection({
  id: "apikeys:main",
  matches: apikeysMatch,
  render: () => {
    const [showKey, setShowKey] = createSignal(false)
    const [showTf, setShowTf] = createSignal(false)

    return (
      <CollapsibleSection title="API Keys">
        <div class="flex flex-col gap-2.5">
          <div class="flex flex-col gap-1">
            <label class="text-[#9a9a9a] text-[13px]">AI Provider</label>
            <Dropdown
              value={activeProvider()}
              options={[{ value: "deepseek" as const, label: "DeepSeek" }]}
              onChange={(v) => { setLLMProvider(v as "deepseek"); saveConfig() }}
            />
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-[#9a9a9a] text-[13px]">API Key</label>
            <div class="flex gap-1">
              <input
                type={showKey() ? "text" : "password"}
                value={llmApiKey()}
                onInput={(e) => { setLLMApiKey(e.currentTarget.value); saveConfig() }}
                class="flex-1 bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40"
                placeholder="sk-..."
              />
              <button
                class="border border-white/20 px-2 py-1 hover:bg-white/10 cursor-pointer shrink-0"
                onClick={() => setShowKey((p) => !p)}
                title={showKey() ? "Hide" : "Show"}
              >
                {showKey() ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                    <circle cx="12" cy="12" r="3"/>
                  </svg>
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                    <line x1="1" y1="1" x2="23" y2="23"/>
                  </svg>
                )}
              </button>
            </div>
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-[#9a9a9a] text-[13px]">TinyFish API Key (optional)</label>
            <div class="flex gap-1">
              <input
                type={showTf() ? "text" : "password"}
                value={tinyfishApiKey()}
                onInput={(e) => { setTinyfishApiKey(e.currentTarget.value); saveConfig() }}
                class="flex-1 bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40"
                placeholder="optional"
              />
              <button
                class="border border-white/20 px-2 py-1 hover:bg-white/10 cursor-pointer shrink-0"
                onClick={() => setShowTf((p) => !p)}
                title={showTf() ? "Hide" : "Show"}
              >
                {showTf() ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                    <circle cx="12" cy="12" r="3"/>
                  </svg>
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                    <line x1="1" y1="1" x2="23" y2="23"/>
                  </svg>
                )}
              </button>
            </div>
          </div>
        </div>
      </CollapsibleSection>
    )
  },
})
