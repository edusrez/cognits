import { createSignal, createResource, Show, createMemo } from "solid-js"
import { highlightCode } from "../lib/markdown"
import "highlight.js/styles/github-dark.css"

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
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export default function CodeView(props: { viewportId?: string; tabId?: string }) {
  const filePath = () => props.tabId?.replace("code:", "") ?? ""
  const fileName = () => filePath().split("/").pop() ?? filePath()

  const [data] = createResource(filePath, fetchFileContent)

  const language = createMemo(() => data()?.language ?? "")

  const highlightedHtml = createMemo(() => {
    const d = data()
    if (!d?.content) return ""
    return highlightCode(d.content, language())
  })

  const lineCount = createMemo(() => {
    const d = data()
    if (!d?.content) return 0
    return d.content.split("\n").length
  })

  return (
    <div class="flex flex-col h-full">
      <div class="flex items-center justify-between px-3 py-1.5 border-b border-white/10 shrink-0"
           style={{ "min-height": "28px" }}>
        <div class="flex items-center gap-2 min-w-0">
          <span class="text-[11px] text-[#6a6a6a] shrink-0">📄</span>
          <span class="text-[12px] text-[#e0e0e0] truncate">{fileName()}</span>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <Show when={language()}>
            <span class="text-[10px] text-[#5a5a5a] border border-white/10 px-1.5 py-0.5 rounded">
              {language()}
            </span>
          </Show>
          <Show when={data()}>
            <span class="text-[10px] text-[#5a5a5a]">{formatSize(data()!.size)}</span>
          </Show>
        </div>
      </div>

      <div class="flex-1 min-h-0 overflow-auto">
        <Show when={!data.loading && !data.error} fallback={
          <Show when={data.loading} fallback={
            <div class="text-[#e74c3c] px-4 py-3 text-[13px]">
              {data.error?.message || "Failed to load file"}
            </div>
          }>
            <div class="text-[#8b949e] px-4 py-3 text-[13px]">Loading...</div>
          </Show>
        }>
          <pre class="m-0" style={{ "tab-size": "4", "font-size": "13px" }}>
            <code class="block px-4 py-3 hljs" innerHTML={highlightedHtml()} style={{ "font-family": "'JetBrains Mono', 'Fira Code', 'Consolas', monospace" }} />
          </pre>
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
