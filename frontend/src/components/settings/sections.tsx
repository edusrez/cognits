/** Auto-registered Settings sections — display-type (self-contained, no context needed).
 *  Add a registerSection() call here to create a new section.
 *  Settings.tsx renders them via For loop. Context menu auto-discovers via hasSettings().
 *
 *  This file is also the barrel that loads the domain section modules
 *  (chat, pdf, general) for their registration side-effects. */

import { Show } from "solid-js"
import { registerSection } from "../../lib/settings-sections"
import SliderField from "../SliderField"
import Dropdown from "../Dropdown"
import CollapsibleSection from "../CollapsibleSection"
import "./chat-sections"   // side-effect: registers chat:info/agent/subagents/shared-data
import "./apikeys-sections" // side-effect: registers apikeys:main
import "./pdf-sections"    // side-effect: registers pdf:ai-vision
import "./general-sections" // side-effect: registers settings:link-prompt + general
import {
  chatFontSize, setChatFontSize,
  noteFontSize, setNoteFontSize,
  reportFontSize, setReportFontSize,
  codeFontSize, setCodeFontSize,
  textFontSize, setTextFontSize,
  pdfZoom, setPdfZoom,
  pdfAIFontSize, setPdfAIFontSize,
  typewriterSpeed, setTypewriterSpeed,
  displayThinking, setDisplayThinking,
  noteMode, setNoteMode,
  writeLangs, setWriteLangs,
  saveConfig,
  beginLinking,
  linkingMode,
  codeWordWrap,
  setCodeWordWrap,
} from "../../stores/settings-store"
import { tabKind } from "../../lib/tab-kinds"

// ── Sessions ──

registerSection({
  id: "sessions:chat-write",
  matches: (ctx) => ctx.linkedViewport && ctx.tabId === "sessions",
  render: () => (
    <CollapsibleSection title="Chat and Write Viewports">
      <div class="flex flex-col gap-2">
        <div class="text-[#9a9a9a] text-[13px]">
          Click &quot;Set&quot; next to each option, then click the viewport you want to link.
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="text-[#9a9a9a]">Viewport for new chats</span>
          <button class="border border-white/20 px-3 py-1 text-[13px] hover:bg-white/10 transition-colors cursor-pointer"
            onClick={() => beginLinking("chat")} disabled={linkingMode()}>Set</button>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="text-[#9a9a9a]">Viewport for new writes</span>
          <button class="border border-white/20 px-3 py-1 text-[13px] hover:bg-white/10 transition-colors cursor-pointer"
            onClick={() => beginLinking("write")} disabled={linkingMode()}>Set</button>
        </div>
      </div>
    </CollapsibleSection>
  ),
})

// ── Project Files (.cognits) ──

registerSection({
  id: "learnit:project-files",
  matches: (ctx) => ctx.linkedViewport && ctx.tabId === "learnit",
  render: () => (
    <CollapsibleSection title="Project Files">
      <div class="flex flex-col gap-2">
        <div class="flex items-center justify-between gap-2">
          <span class="text-[#9a9a9a]">Viewport linked to Reports &amp; Notes</span>
          <button class="border border-white/20 px-3 py-1 text-[13px] hover:bg-white/10 transition-colors cursor-pointer"
            onClick={() => beginLinking("learnit")} disabled={linkingMode()}>Change</button>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="text-[#9a9a9a]">Viewport linked to Files</span>
          <button class="border border-white/20 px-3 py-1 text-[13px] hover:bg-white/10 transition-colors cursor-pointer"
            onClick={() => beginLinking("files")} disabled={linkingMode()}>Change</button>
        </div>
      </div>
    </CollapsibleSection>
  ),
})

// ── Files ──

registerSection({
  id: "files:viewport",
  matches: (ctx) => ctx.linkedViewport && ctx.tabId === "files",
  render: () => (
    <CollapsibleSection title="Files">
      <div class="flex flex-col gap-2">
        <div class="flex items-center justify-between gap-2">
          <span class="text-[#9a9a9a]">Viewport linked to</span>
          <button class="border border-white/20 px-3 py-1 text-[13px] hover:bg-white/10 transition-colors cursor-pointer"
            onClick={() => beginLinking("files")} disabled={linkingMode()}>Change</button>
        </div>
      </div>
    </CollapsibleSection>
  ),
})

// ── Write ──

registerSection({
  id: "write:langs",
  matches: (ctx) => ctx.linkedViewport && ctx.tabId === "write",
  render: () => (
    <CollapsibleSection title="Write">
      <div class="flex flex-col gap-2">
        <div class="text-[#9a9a9a]">Spell Check Languages</div>
        {(["es", "en"] as const).map((lang) => {
          const active = () => writeLangs().includes(lang)
          return (
            <button class="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-white/10 transition-colors cursor-pointer"
              onClick={() => {
                if (active()) setWriteLangs(writeLangs().filter((l) => l !== lang))
                else setWriteLangs([...writeLangs(), lang])
                saveConfig()
              }}>
              <span class="text-[13px] text-[#e0e0e0]">{lang.toUpperCase()}</span>
              <span class="ml-auto text-[11px] text-[#6a6a6a]">{active() ? "On" : "Off"}</span>
            </button>
          )
        })}
      </div>
    </CollapsibleSection>
  ),
})

// ── PDF Display ──

registerSection({
  id: "pdf:display",
  matches: (ctx) => ctx.linkedViewport && tabKind(ctx.tabId) === "pdf",
  render: () => (
    <CollapsibleSection title="Display">
      <div class="flex flex-col gap-2">
        <SliderField label="Raw zoom" value={pdfZoom()}
          onInput={(v) => { setPdfZoom(v); saveConfig() }} min={50} max={400} step={10}
          formatValue={(v) => `${v}%`} />
        <SliderField label="AI text size" value={pdfAIFontSize()}
          onInput={(v) => { setPdfAIFontSize(v); saveConfig() }} min={11} max={24} step={1}
          formatValue={(v) => `${v}px`} />
      </div>
    </CollapsibleSection>
  ),
})

// ── Chat Display ──

registerSection({
  id: "chat:display",
  matches: (ctx) => ctx.linkedViewport && ctx.tabId === "chat",
  render: () => (
    <CollapsibleSection title="Display">
      <div class="flex flex-col gap-2">
        <SliderField label="Text size" value={chatFontSize()}
          onInput={(v) => { setChatFontSize(v); saveConfig() }} min={11} max={24} step={1}
          formatValue={(v) => `${v}px`} />
        <SliderField label="Typewriter speed" value={typewriterSpeed()}
          onInput={(v) => { setTypewriterSpeed(v); saveConfig() }} min={0.01} max={10} step={0.01}
          formatValue={(v) => `${v.toFixed(2)}ms`} />
        <div class="flex items-center justify-between gap-2">
          <span class="text-[#9a9a9a]">Show thinking</span>
          <div class="flex gap-1">
            {(["show", "hide"] as const).map((m) => {
              const on = m === "show"
              return (
                <button class={`border border-white/20 px-3 py-1.5 text-[13px] transition-colors cursor-pointer whitespace-nowrap ${displayThinking() === on ? "bg-white/10 text-[#e0e0e0]" : "hover:bg-white/5 text-[#6a6a6a]"}`}
                  onClick={() => { setDisplayThinking(on); saveConfig() }}>
                  {m === "show" ? "Show" : "Hide"}
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </CollapsibleSection>
  ),
})

// ── Code Display ──

registerSection({
  id: "code:display",
  matches: (ctx) => ctx.linkedViewport && tabKind(ctx.tabId) === "code",
  render: () => (
    <CollapsibleSection title="Display">
      <div class="flex flex-col gap-2">
        <SliderField label="Text size" value={codeFontSize()}
          onInput={(v) => { setCodeFontSize(v); saveConfig() }} min={11} max={24} step={1}
          formatValue={(v) => `${v}px`} />
        <div class="flex items-center justify-between gap-2">
          <label class="text-[#9a9a9a] text-[13px]">Word wrap</label>
        </div>
        <Dropdown
          value={codeWordWrap() ? "on" : "off"}
          options={[{ value: "on", label: "On" }, { value: "off", label: "Off" }]}
          onChange={(v) => { setCodeWordWrap(v === "on"); saveConfig() }}
        />
      </div>
    </CollapsibleSection>
  ),
})

// ── Text Display ──

registerSection({
  id: "text:display",
  matches: (ctx) => ctx.linkedViewport && tabKind(ctx.tabId) === "text",
  render: () => (
    <CollapsibleSection title="Display">
      <div class="flex flex-col gap-2">
        <SliderField label="Text size" value={textFontSize()}
          onInput={(v) => { setTextFontSize(v); saveConfig() }} min={11} max={24} step={1}
          formatValue={(v) => `${v}px`} />
      </div>
    </CollapsibleSection>
  ),
})

// ── Note Display ──

registerSection({
  id: "note:display",
  matches: (ctx) => ctx.linkedViewport && tabKind(ctx.tabId) === "note",
  render: () => (
    <CollapsibleSection title="Display">
      <div class="flex flex-col gap-2">
        <SliderField label="Text size" value={noteFontSize()}
          onInput={(v) => { setNoteFontSize(v); saveConfig() }} min={11} max={24} step={1}
          formatValue={(v) => `${v}px`} />
        <div class="text-[#9a9a9a]">Note mode</div>
        {(["edit", "view"] as const).map((mode) => {
          const active = () => noteMode() === mode
          return (
            <button class="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-white/10 transition-colors cursor-pointer"
              onClick={() => { setNoteMode(mode); saveConfig() }}>
              <span class="text-[13px] text-[#e0e0e0]">{mode === "edit" ? "Edit Mode" : "View Mode"}</span>
              <span class="ml-auto text-[11px] text-[#6a6a6a]">{active() ? "Active" : ""}</span>
            </button>
          )
        })}
      </div>
    </CollapsibleSection>
  ),
})

// ── Report Display ──

registerSection({
  id: "report:display",
  matches: (ctx) => ctx.linkedViewport && tabKind(ctx.tabId) === "report",
  render: () => (
    <CollapsibleSection title="Display">
      <div class="flex flex-col gap-2">
        <SliderField label="Text size" value={reportFontSize()}
          onInput={(v) => { setReportFontSize(v); saveConfig() }} min={11} max={24} step={1}
          formatValue={(v) => `${v}px`} />
      </div>
    </CollapsibleSection>
  ),
})
