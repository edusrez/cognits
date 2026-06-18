/** PDF-linked Settings sections — AI Vision (docling conversion options).
 *  Matches ctx.tabId === "pdf" with a linked viewport. The re-render button
 *  depends on the per-instance pdfPath, which the shell injects as a reactive
 *  accessor in SectionContext (render() runs once per section, so a plain
 *  string would go stale when the user switches PDFs). */

import { Show, For } from "solid-js"
import { registerSection, type SectionContext } from "../../lib/settings-sections"
import { tabKind } from "../../lib/tab-kinds"
import SliderField from "../SliderField"
import Dropdown from "../Dropdown"
import CollapsibleSection from "../CollapsibleSection"
import {
  doclingTableMode, setDoclingTableMode,
  doclingImageScale, setDoclingImageScale,
  doclingOcr, setDoclingOcr,
  doclingCodeEnrich, setDoclingCodeEnrich,
  doclingFormulaEnrich, setDoclingFormulaEnrich,
  doclingPictureClassify, setDoclingPictureClassify,
  doclingForceText, setDoclingForceText,
  doclingPreset, setDoclingPreset,
  applyDoclingPreset,
  doclingDirty, setDoclingDirty,
  doclingRefreshTrigger, setDoclingRefreshTrigger,
  saveConfig,
} from "../../stores/settings-store"

registerSection({
  id: "pdf:ai-vision",
  matches: (ctx) => ctx.linkedViewport && tabKind(ctx.tabId) === "pdf",
  render: (ctx: SectionContext) => (
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

        <Show when={doclingDirty() && ctx.pdfPath?.()}>
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
  ),
})
