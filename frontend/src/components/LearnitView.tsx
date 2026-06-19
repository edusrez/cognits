import { For, Show, createMemo, createSignal, createEffect, onMount } from "solid-js"
import {
  reports, searchResults, totalPages, totalResults, currentPage,
  setSearch, setSort, sortBy, goToPage, refetchReports,
} from "../stores/learnit-store"
import { notes, loadNotes, createNote, renameNote, deleteNote, type Note } from "../stores/notebook-store"
import { defaultLearnitViewport } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import { listDragState, initiateListDrag, moveHint } from "../drag/drag-state"
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
    { value: "date_desc" as const, label: "Date (newest)" },
    { value: "date_asc" as const, label: "Date (oldest)" },
    { value: "title_asc" as const, label: "Title (A-Z)" },
    { value: "title_desc" as const, label: "Title (Z-A)" },
  ]

  onMount(() => {
    loadNotes()
  })

  const handleCreateSheet = () => {
    const n = notes().length + 1
    createNote(`Note ${n}`)
  }

  const ds = () => listDragState()

  const displayNotes = createMemo(() => {
    const all = notes()
    const mh = moveHint()
    if (mh && mh.listId === "notebook") {
      const filtered = all.filter((n) => n.id !== mh.itemId)
      const idx = Math.min(mh.targetIndex, filtered.length)
      const item = all.find((n) => n.id === mh.itemId)
      const ghost: Note = { id: "__ghost__", title: item?.title ?? "", content: "", createdAt: "", updatedAt: "" }
      return [...filtered.slice(0, idx), ghost, ...filtered.slice(idx)]
    }
    if (!ds().isDragging || ds().listId !== "notebook") return all
    const filtered = all.filter((n) => n.id !== ds().itemId)
    const idx = Math.min(ds().insertIndex >= 0 ? ds().insertIndex : filtered.length, filtered.length)
    const ghost: Note = { id: "__ghost__", title: ds().itemLabel, content: "", createdAt: "", updatedAt: "" }
    return [...filtered.slice(0, idx), ghost, ...filtered.slice(idx)]
  })

  const onNoteMouseDown = (note: Note, e: MouseEvent) => {
    initiateListDrag(note.id, note.title, "notebook", e)
  }

  const [renaming, setRenaming] = createSignal<string | null>(null)

  const noteMenu = createMemo(() => {
    const m = ctxMenu()
    if (m?.kind === "note") return m
    return null
  })

  const onNoteContextMenu = (e: MouseEvent, noteId: string) => {
    e.preventDefault()
    e.stopPropagation()
    setCtxMenu({ kind: "note", noteId, x: e.clientX, y: e.clientY })
  }

  const startRenaming = () => {
    const m = ctxMenu()
    if (m?.kind === "note") {
      setRenaming(m.noteId)
      setCtxMenu(null)
    }
  }

  const handleDeleteNote = () => {
    const m = ctxMenu()
    if (m?.kind === "note") {
      deleteNote(m.noteId)
      setCtxMenu(null)
    }
  }

  const onRenameKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      ;(e.currentTarget as HTMLTextAreaElement).blur()
    }
  }

  const onRenameBlur = (e: FocusEvent, id: string) => {
    const target = e.currentTarget as HTMLTextAreaElement
    const name = target.value.trim()
    if (name) {
      renameNote(id, name)
    }
    setRenaming(null)
  }

  const adjustHeight = (el: HTMLTextAreaElement) => {
    el.style.height = "auto"
    el.style.height = el.scrollHeight + "px"
  }

  return (
    <div class="h-full overflow-y-auto p-3 text-[13px] flex flex-col gap-3">
      <CollapsibleSection title="Notebook">
        <div class="flex flex-col gap-2" data-list-id="notebook">
          <button
            class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors w-full text-left cursor-pointer"
            onClick={handleCreateSheet}
          >
            + Create Sheet
          </button>

          <For each={displayNotes()}>
            {(item) => (
              <Show
                when={item.id === "__ghost__"}
                fallback={
                  <Show
                    when={renaming() === item.id}
                    fallback={
                      <button
                        data-note-id={item.id}
                        data-drag-item=""
                        class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors w-full text-left whitespace-pre-wrap cursor-pointer"
                        classList={{
                          "list-drag-dimmed": ds().isDragging && ds().listId === "notebook" && item.id !== ds().itemId,
                        }}
                        onMouseDown={(e) => onNoteMouseDown(item, e)}
                        onClick={() => {
                          if (ds().isDragging) return
                          import("../stores/notebook-store").then((m) =>
                            m.openNoteInViewport(defaultLearnitViewport(), item.id),
                          )
                        }}
                        onContextMenu={(e) => onNoteContextMenu(e, item.id)}
                      >
                        {item.title}
                      </button>
                    }
                  >
                    <textarea
                      data-drag-item=""
                      class="border border-white/20 px-3 py-1.5 text-[13px] bg-transparent text-[#e0e0e0] w-full resize-none outline-none overflow-hidden"
                      classList={{
                        "list-drag-dimmed": ds().isDragging && ds().listId === "notebook" && item.id !== ds().itemId,
                      }}
                      rows={1}
                      maxLength={120}
                      onKeyDown={onRenameKeyDown}
                      onBlur={(e) => onRenameBlur(e, item.id)}
                      onInput={(e) => adjustHeight(e.currentTarget)}
                      ref={(el) => {
                        if (el instanceof HTMLTextAreaElement) {
                          el.value = item.title
                          requestAnimationFrame(() => {
                            el.focus()
                            el.setSelectionRange(el.value.length, el.value.length)
                            adjustHeight(el)
                          })
                        }
                      }}
                    />
                  </Show>
                }
              >
                <div
                  data-drag-ghost=""
                  class="border border-white/20 px-3 py-1.5 text-[13px] list-drag-ghost w-full text-left whitespace-pre-wrap"
                >
                  {item.title}
                </div>
              </Show>
            )}
          </For>
        </div>
      </CollapsibleSection>

      <Show when={noteMenu()}>
        {(m) => (
          <ContextMenu
            x={m().x}
            y={m().y}
            onClose={() => setCtxMenu(null)}
            items={[
              { label: "Rename", onClick: startRenaming },
              { label: "Delete", onClick: handleDeleteNote, class: "text-red-400" },
            ]}
          />
        )}
      </Show>

      <CollapsibleSection title="Reports">
        <div class="flex flex-col gap-2">
          <input
            type="text"
            placeholder="Search reports..."
            onInput={(e) => setSearch(e.currentTarget.value)}
            class="bg-transparent border border-white/20 px-2 py-1 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40"
          />

          <div class="flex items-center gap-1 text-[#9a9a9a]">
            <span>Sort:</span>
            <Dropdown
              value={sortBy()}
              options={sortOptions}
              onChange={(v) => setSort(v)}
              class="w-44"
            />
            <span class="ml-auto text-[#6a6a6a]">
              {totalResults()} result{totalResults() !== 1 ? "s" : ""}
            </span>
          </div>

          <Show
            when={displayReports().length > 0 || !searchResults.loading}
            fallback={<div class="text-[#6a6a6a]">Loading...</div>}
          >
            <For each={displayReports()}>
              {(report: any) => (
                <div
                  data-report-id={report.id}
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
                {" Previous"}
              </button>
              <span class="text-[#9a9a9a]">
                Page {currentPage()} of {totalPages()}
              </span>
              <button
                class="border border-white/20 px-2 py-0.5 text-[13px] hover:bg-white/10 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                disabled={currentPage() >= totalPages()}
                onClick={() => goToPage(currentPage() + 1)}
              >
                {"Next "}
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
                label: "Open",
                onClick: () => {
                  const reportId = m().reportId
                  setCtxMenu(null)
                  import("../stores/report-store").then((rm) =>
                    rm.openReportInViewport(defaultLearnitViewport(), reportId),
                  )
                },
              },
              {
                label: "Delete",
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
