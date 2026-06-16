import { createSignal, createResource, createEffect, createMemo, Show, onCleanup, For } from "solid-js"
import * as pdfjs from "pdfjs-dist"
import pdfjsWorker from "pdfjs-dist/build/pdf.worker.mjs?url"
import MarkdownView from "./MarkdownView"
import { doclingRefreshTrigger } from "../stores/settings-store"

pdfjs.GlobalWorkerOptions.workerSrc = pdfjsWorker

interface FileContent {
  path: string
  category: string
  language: string | null
  mime: string
  size: number
  content: string | null
  stream_url: string | null
}

async function fetchAiContent(path: string, force: boolean): Promise<FileContent> {
  let url = `/api/files/content?path=${encodeURIComponent(path)}&mode=ai`
  if (force) url += "&force=true"
  const res = await fetch(url)
  if (!res.ok) {
    const msg = await res.text()
    throw new Error(msg.trim() || `HTTP ${res.status}`)
  }
  return res.json()
}

async function fetchRawMeta(path: string): Promise<FileContent> {
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

export default function PdfView(props: { viewportId?: string; tabId?: string }) {
  const filePath = () => props.tabId?.replace("pdf:", "") ?? ""
  const fileName = () => filePath().split("/").pop() ?? filePath()

  const [mode, setMode] = createSignal<"raw" | "ai">("raw")

  const [forceAi, setForceAi] = createSignal(false)

  const [rawMeta] = createResource(() => mode() === "raw" ? filePath() : null, fetchRawMeta)
  const [aiContent] = createResource(
    () => mode() === "ai" ? [filePath(), doclingRefreshTrigger()] as const : null,
    ([path]) => {
      const f = forceAi()
      setForceAi(false)
      return fetchAiContent(path, f)
    }
  )

  const streamUrl = createMemo(() => rawMeta()?.stream_url ?? "")

  // PDF.js rendering for raw mode
  const [numPages, setNumPages] = createSignal(0)
  const [pdfError, setPdfError] = createSignal<string | null>(null)
  const [pdfLoading, setPdfLoading] = createSignal(false)
  let pdfDoc: pdfjs.PDFDocumentProxy | null = null

  createEffect(() => {
    if (mode() !== "raw") return
    const url = `/api/files/raw?path=${encodeURIComponent(filePath())}`

    setPdfLoading(true)
    setPdfError(null)
    setNumPages(0)

    pdfjs.getDocument(url).promise.then((doc) => {
      pdfDoc = doc
      setNumPages(doc.numPages)
      setPdfLoading(false)
    }).catch((err) => {
      setPdfError(err.message || "Failed to load PDF")
      setPdfLoading(false)
    })
  })

  onCleanup(() => {
    if (pdfDoc) {
      pdfDoc.destroy()
      pdfDoc = null
    }
  })

  // Render a single page canvas
  function renderPage(pageNum: number, canvas: HTMLCanvasElement) {
    if (!pdfDoc) return
    pdfDoc.getPage(pageNum).then((page) => {
      const viewport = page.getViewport({ scale: 1.5 })
      canvas.width = viewport.width
      canvas.height = viewport.height
      page.render({ canvas, viewport }).promise
    }).catch(() => {
      // silently ignore render errors for destroyed pages
    })
  }

  const pageNumbers = createMemo(() => {
    const n = numPages()
    if (n <= 0) return []
    return Array.from({ length: n }, (_, i) => i + 1)
  })

  // AI mode markdown
  const aiMarkdown = createMemo(() => aiContent()?.content ?? "")

  return (
    <div class="flex flex-col h-full">
      {/* Header with toggle */}
      <div class="flex items-center justify-between px-4 py-2 shrink-0">
        <span class="text-[13px] text-[#9a9a9a] truncate">{fileName()}</span>

        <div class="flex items-center gap-2 shrink-0">
          <Show when={rawMeta()}>
            <span class="text-[10px] text-[#5a5a5a]">{formatSize(rawMeta()!.size)}</span>
          </Show>

          <div class="flex items-center gap-1">
            {(["raw", "ai"] as const).map((m) => (
              <button
                class={`border border-white/20 px-3 py-1.5 text-[13px] transition-colors cursor-pointer whitespace-nowrap ${
                  mode() === m
                    ? "bg-white/10 text-[#e0e0e0]"
                    : "hover:bg-white/5 text-[#6a6a6a]"
                }`}
                onClick={() => setMode(m)}
              >
                {m === "raw" ? "Raw" : "AI"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content area */}
      <div class="flex-1 min-h-0 p-2 overflow-auto bg-[#0d0d0d]">
        <Show when={mode() === "raw"} fallback={
          /* AI mode */
          <Show when={!aiContent.loading && !aiContent.error} fallback={
            <Show when={aiContent.loading} fallback={
              <div class="text-[#e74c3c] px-4 py-3 text-[13px]">
                {aiContent.error?.message || "Conversion failed"}
              </div>
            }>
              <div class="text-[#8b949e] px-4 py-3 text-[13px]">
                Converting PDF to markdown...
              </div>
            </Show>
          }>
            <div class="px-4 py-3 chat-markdown" style={{ "font-size": "14px" }}>
              <MarkdownView content={aiMarkdown()} />
            </div>
          </Show>
        }>
          {/* Raw mode */}
          <Show when={!pdfLoading() && !pdfError()} fallback={
            <Show when={pdfLoading()} fallback={
              <div class="text-[#e74c3c] px-4 py-3 text-[13px]">
                {pdfError()}
              </div>
            }>
              <div class="text-[#8b949e] px-4 py-3 text-[13px]">Loading PDF...</div>
            </Show>
          }>
            <div class="flex flex-col items-center py-4 gap-1">
              <For each={pageNumbers()}>
                {(pageNum) => (
                  <canvas
                    ref={(el) => { renderPage(pageNum, el) }}
                    class="shadow-lg"
                    style={{ "max-width": "100%", "margin-bottom": "1px" }}
                  />
                )}
              </For>
            </div>
          </Show>
        </Show>
      </div>
    </div>
  )
}
