import { createSignal, createResource, Show, createMemo } from "solid-js"
import { escapeHtmlSafe } from "../lib/markdown"
import { textFontSize, setTextFontSize, saveConfig } from "../stores/settings-store"

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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function TextView(props: { viewportId?: string; tabId?: string }) {
  const filePath = () => props.tabId?.replace("text:", "") ?? ""
  const fileName = () => filePath().split("/").pop() ?? filePath()

  const [data] = createResource(filePath, fetchFileContent)

  const [error, setError] = createSignal<string | null>(null)

  const renderedContent = createMemo(() => {
    const d = data()
    if (!d?.content) return ""
    const content = d.content
    const escaped = escapeHtmlSafe(content)
    return escaped
  })

  return (
    <div class="flex flex-col h-full">
      <div class="flex items-center justify-between px-4 py-2 shrink-0">
        <span class="text-[13px] text-[#9a9a9a] truncate">{fileName()}</span>
        <Show when={data()}>
          <span class="text-[10px] text-[#5a5a5a] shrink-0">{formatSize(data()!.size)}</span>
        </Show>
      </div>

      <div class="flex-1 min-h-0 p-2 overflow-auto"
       onWheel={(e) => {
         if (!e.shiftKey) return
         e.preventDefault()
         const delta = e.deltaY > 0 ? -1 : 1
         setTextFontSize(Math.max(11, Math.min(24, textFontSize() + delta)))
         saveConfig()
       }}>
        <Show when={!error() && !data.loading} fallback={
          <Show when={data.loading} fallback={
            <div class="text-[#e74c3c] px-4 py-3 text-[13px]">{error() || "Failed to load file"}</div>
          }>
            <div class="text-[#8b949e] px-4 py-3 text-[13px]">Loading...</div>
          </Show>
        }>
          <pre class="px-4 py-3 text-[#e0e0e0] whitespace-pre-wrap break-words m-0"
               style={{ "font-family": "system-ui, sans-serif", "tab-size": "4", "font-size": `${textFontSize()}px` }}
               innerHTML={renderedContent()} />
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
