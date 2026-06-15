import { createSignal, createResource, Show, createMemo } from "solid-js"

interface FileMeta {
  path: string
  category: string
  language: string | null
  mime: string
  size: number
  content: string | null
  stream_url: string | null
}

async function fetchFileMeta(path: string): Promise<FileMeta> {
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

export default function ImageView(props: { viewportId?: string; tabId?: string }) {
  const filePath = () => props.tabId?.replace("image:", "") ?? ""
  const fileName = () => filePath().split("/").pop() ?? filePath()

  const [data] = createResource(filePath, fetchFileMeta)

  const [lightbox, setLightbox] = createSignal(false)
  const [imgSize, setImgSize] = createSignal<{ w: number; h: number } | null>(null)

  function onImgLoad(e: Event) {
    const img = e.currentTarget as HTMLImageElement
    setImgSize({ w: img.naturalWidth, h: img.naturalHeight })
  }

  const streamUrl = createMemo(() => data()?.stream_url ?? "")

  return (
    <div class="flex flex-col h-full">
      <div class="flex items-center justify-between px-4 py-2 shrink-0">
        <span class="text-[13px] text-[#9a9a9a] truncate">{fileName()}</span>
        <Show when={data()}>
          <span class="text-[10px] text-[#5a5a5a] shrink-0">{formatSize(data()!.size)}</span>
        </Show>
      </div>

      <div class="flex-1 min-h-0 p-2 flex items-center justify-center overflow-auto bg-[#0d0d0d]">
        <Show when={!data.loading && !data.error} fallback={
          <Show when={data.loading} fallback={
            <div class="text-[#e74c3c] px-4 py-3 text-[13px]">
              {data.error?.message || "Failed to load image"}
            </div>
          }>
            <div class="text-[#8b949e] text-[13px]">Loading...</div>
          </Show>
        }>
          <Show when={streamUrl()}>
            <img
              src={streamUrl()}
              alt={fileName()}
              onLoad={onImgLoad}
              onError={() => data.error = { message: "Failed to load image" } as any}
              class="max-w-full max-h-full object-contain cursor-pointer"
              onClick={() => setLightbox(true)}
            />
          </Show>
        </Show>
      </div>

      <Show when={imgSize()}>
        <div class="flex items-center justify-between px-3 py-1 border-t border-white/5 shrink-0 bg-white/[0.02]">
          <span class="text-[10px] text-[#5a5a5a]">
            {imgSize()!.w} × {imgSize()!.h}
          </span>
          <span class="text-[10px] text-[#5a5a5a]">{data()?.mime}</span>
        </div>
      </Show>

      <Show when={lightbox()}>
        <div
          class="fixed inset-0 z-50 bg-black/90 flex items-center justify-center cursor-pointer"
          onClick={() => setLightbox(false)}
        >
          <img
            src={streamUrl()}
            alt={fileName()}
            class="max-w-[95vw] max-h-[95vh] object-contain"
          />
        </div>
      </Show>
    </div>
  )
}
