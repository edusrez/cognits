import { createSignal, createResource, Show, createMemo } from "solid-js"
import { highlightCode } from "../lib/markdown"
import { codeFontSize, setCodeFontSize, saveConfig } from "../stores/settings-store"
import MarkdownView from "./MarkdownView"
import "../highlight-theme.css"

interface FileContent {
  path: string
  category: string
  language: string | null
  mime: string
  size: number
  content: string | null
  stream_url: string | null
  truncated?: boolean
}

async function fetchFileContent(path: string): Promise<FileContent> {
  const res = await fetch(`/api/files/content?path=${encodeURIComponent(path)}&mode=raw`)
  if (!res.ok) {
    const msg = await res.text()
    throw new Error(msg.trim() || `HTTP ${res.status}`)
  }
  return res.json()
}

export default function CodeView(props: { viewportId?: string; tabId?: string }) {
  const filePath = () => props.tabId?.replace("code:", "") ?? ""
  const fileName = () => filePath().split("/").pop() ?? filePath()

  const [data] = createResource(filePath, fetchFileContent)

  const language = createMemo(() => data()?.language ?? "")
  const isMarkdown = createMemo(() => language() === "markdown")
  const [mdMode, setMdMode] = createSignal<"plain" | "markdown">("plain")

  const highlightedHtml = createMemo(() => {
    const d = data()
    if (!d?.content) return ""
    return highlightCode(d.content, language())
  })

  return (
    <div class="flex flex-col h-full">
      <div class="flex items-center justify-between px-4 py-2 shrink-0">
        <span class="text-[13px] text-[#9a9a9a] truncate">{fileName()}</span>
        <Show when={isMarkdown()}>
          <div class="flex items-center gap-1">
            {(["plain", "markdown"] as const).map((m) => (
              <button
                class={`border border-white/20 px-3 py-1.5 text-[13px] transition-colors cursor-pointer whitespace-nowrap ${
                  mdMode() === m
                    ? "bg-white/10 text-[#e0e0e0]"
                    : "hover:bg-white/5 text-[#6a6a6a]"
                }`}
                onClick={() => setMdMode(m)}
              >
                {m === "plain" ? "Plain Text" : "Markdown"}
              </button>
            ))}
          </div>
        </Show>
      </div>

      <div class="flex-1 min-h-0 p-2 overflow-auto"
           onWheel={(e) => {
             if (!e.shiftKey) return
             e.preventDefault()
             const delta = e.deltaY > 0 ? -1 : 1
             setCodeFontSize(Math.max(11, Math.min(24, codeFontSize() + delta)))
             saveConfig()
           }}>
        <Show when={!data.loading && !data.error} fallback={
          <Show when={data.loading} fallback={
            <div class="text-[#e74c3c] px-4 py-3 text-[13px]">
              {data.error?.message || "Failed to load file"}
            </div>
          }>
            <div class="text-[#8b949e] px-4 py-3 text-[13px]">Loading...</div>
          </Show>
        }>
          <Show when={!isMarkdown() || mdMode() === "plain"} fallback={
            <div class="px-4 py-3 chat-markdown" style={{ "font-size": `${codeFontSize()}px` }}>
              <MarkdownView content={data()!.content ?? ""} />
            </div>
          }>
            <pre class="m-0" style={{ "tab-size": "4", "font-size": `${codeFontSize()}px` }}>
              <code class="block px-4 py-3 hljs" innerHTML={highlightedHtml()} style={{ "font-family": "'JetBrains Mono', 'Fira Code', 'Consolas', monospace" }} />
            </pre>
          </Show>
        </Show>
      </div>

      <Show when={data()?.truncated}>
        <div class="text-[10px] text-[#f0c040] px-3 py-1 border-t border-white/5 shrink-0 bg-white/[0.02]">
          File truncated at 5 MB
        </div>
      </Show>
    </div>
  )
}
