import { For, Show, createMemo, createSignal, createEffect } from "solid-js"
import {
  reports, searchResults, totalPages, totalResults, currentPage,
  setSearch, setSort, sortBy, goToPage, refetchReports,
} from "../stores/learnit-store"
import { defaultLearnitViewport } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import ContextMenu from "./ContextMenu"
import CollapsibleSection from "./CollapsibleSection"
import Dropdown from "./Dropdown"
import { sanitizeHighlight } from "../lib/markdown"

function renderHighlighted(html: string) {
  return <span innerHTML={sanitizeHighlight(html)} />
}

export default function LearnitView() {
  const [cachedReports, setCachedReports] = createSignal<any[]>([])

  createEffect(() => {
    const r = searchResults()
    if (r && !searchResults.loading) {
      setCachedReports(r.reports)
    }
  })

  const displayReports = () =>
    searchResults.loading && cachedReports().length > 0 ? cachedReports() : reports()

  const reportMenu = createMemo(() => {
    const m = ctxMenu()
    if (m?.kind === "report") return m
    return null
  })

  const sortOptions = [
    { value: "date_desc" as const, label: "Fecha (más reciente)" },
    { value: "date_asc" as const, label: "Fecha (más antiguo)" },
    { value: "title_asc" as const, label: "Título (A-Z)" },
    { value: "title_desc" as const, label: "Título (Z-A)" },
  ]

  return (
    <div class="h-full overflow-y-auto px-3 py-2 text-[13px]">
      <CollapsibleSection title="Informes" defaultOpen={true}>
        <div class="flex flex-col gap-2">
          <input
            type="text"
            placeholder="Buscar informes..."
            onInput={(e) => setSearch(e.currentTarget.value)}
            class="bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40"
          />

          <div class="flex items-center gap-1 text-[#9a9a9a]">
            <span>Ordenar:</span>
            <Dropdown
              value={sortBy()}
              options={sortOptions}
              onChange={(v) => setSort(v)}
              class="w-44"
            />
            <span class="ml-auto text-[#6a6a6a]">
              {totalResults()} resultado{totalResults() !== 1 ? "s" : ""}
            </span>
          </div>

          <Show
            when={displayReports().length > 0 || !searchResults.loading}
            fallback={<div class="text-[#6a6a6a]">Cargando...</div>}
          >
            <For each={displayReports()}>
              {(report: any) => (
                <div
                  class="border border-white/20 px-3 py-1.5 cursor-pointer hover:bg-white/5"
                  onClick={() => {
                    import("../stores/report-store").then((m) =>
                      m.openReportInViewport(defaultLearnitViewport(), report.id),
                    )
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    setCtxMenu({
                      kind: "report",
                      reportId: report.id,
                      reportTitle: report.title,
                      x: e.clientX,
                      y: e.clientY,
                    })
                  }}
                >
                  <div>
                    {report.titleHighlighted
                      ? renderHighlighted(report.titleHighlighted)
                      : report.title}
                  </div>
                  <div class="text-[#6a6a6a] text-[11px]">
                    {report.createdAt}
                  </div>
                </div>
              )}
            </For>
          </Show>

          <Show when={totalPages() > 1}>
            <div class="flex items-center justify-center gap-3 mt-1">
              <button
                class="border border-white/20 px-2 py-0.5 text-[13px] hover:bg-white/10 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                disabled={currentPage() <= 1}
                onClick={() => goToPage(currentPage() - 1)}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
                {" Anterior"}
              </button>
              <span class="text-[#9a9a9a]">
                Pág. {currentPage()} de {totalPages()}
              </span>
              <button
                class="border border-white/20 px-2 py-0.5 text-[13px] hover:bg-white/10 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                disabled={currentPage() >= totalPages()}
                onClick={() => goToPage(currentPage() + 1)}
              >
                {"Siguiente "}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
            </div>
          </Show>
        </div>
      </CollapsibleSection>

      <Show when={reportMenu()}>
        {(m) => (
          <ContextMenu
            x={m().x}
            y={m().y}
            onClose={() => setCtxMenu(null)}
            items={[
              {
                label: "Abrir",
                onClick: () => {
                  const reportId = m().reportId
                  setCtxMenu(null)
                  import("../stores/report-store").then((rm) =>
                    rm.openReportInViewport(defaultLearnitViewport(), reportId),
                  )
                },
              },
              {
                label: "Eliminar Informe",
                class: "text-red-400",
                onClick: async () => {
                  const reportId = m().reportId
                  setCtxMenu(null)
                  await fetch(`/api/reports/${reportId}`, { method: "DELETE" })
                  refetchReports()
                },
              },
            ]}
          />
        )}
      </Show>
    </div>
  )
}
