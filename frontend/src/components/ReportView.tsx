import { createResource, Show, createMemo } from "solid-js"
import { loadReport } from "../stores/report-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import ContextMenu from "./ContextMenu"
import MarkdownView from "./MarkdownView"
import { copyToClipboard } from "../lib/clipboard"

export default function ReportView(props: { viewportId?: string; tabId?: string }) {
  const reportId = () => props.tabId?.replace("report:", "") ?? ""
  const [report] = createResource(reportId, loadReport)

  const reportContentMenu = createMemo(() => {
    const m = ctxMenu()
    if (m?.kind === "report-content") return m
    return null
  })

  return (
    <div
      class="h-full overflow-y-auto px-4 py-3 chat-markdown"
      style={{ "font-size": "13px" }}
      onContextMenu={(e) => {
        const r = report()
        if (!r) return
        e.preventDefault()
        e.stopPropagation()
        setCtxMenu({
          kind: "report-content",
          content: r.content,
          reportId: reportId(),
          title: r.title,
          x: e.clientX,
          y: e.clientY,
        })
      }}
    >
      <Show
        when={report()}
        fallback={<div class="text-[#8b949e]">Loading report...</div>}
      >
        {(r) => (
          <MarkdownView content={r().content} />
        )}
      </Show>

      <Show when={reportContentMenu()}>
        {(m) => (
          <ContextMenu
            x={m().x}
            y={m().y}
            onClose={() => setCtxMenu(null)}
            items={[
              {
                label: "Copy in Markdown",
                onClick: () => {
                  const text = m().content
                  setCtxMenu(null)
                  copyToClipboard(text)
                },
              },
            ]}
          />
        )}
      </Show>
    </div>
  )
}
