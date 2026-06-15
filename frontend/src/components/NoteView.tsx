import { Show, createResource, createSignal, createEffect, onCleanup } from "solid-js"
import { loadNote, saveNoteContent, renameNote } from "../stores/notebook-store"
import { noteMode, setNoteMode, saveConfig, noteFontSize } from "../stores/settings-store"
import MarkdownView from "./MarkdownView"

function adjustHeight(el: HTMLTextAreaElement) {
  el.style.height = "auto"
  el.style.height = el.scrollHeight + "px"
}

export default function NoteView(props: { viewportId?: string; tabId?: string }) {
  const noteId = () => props.tabId?.replace("note:", "") ?? ""

  const [note, { mutate }] = createResource(noteId, loadNote)

  const [editContent, setEditContent] = createSignal("")
  const [renaming, setRenaming] = createSignal(false)

  createEffect(() => {
    const n = note()
    if (n && !note.loading) setEditContent(n.content)
  })

  let saveTimer: ReturnType<typeof setTimeout> | null = null

  const onInput = (content: string) => {
    setEditContent(content)
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => {
      saveNoteContent(noteId(), content)
    }, 5000)
  }

  onCleanup(() => {
    if (saveTimer) clearTimeout(saveTimer)
  })

  const onRenameKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      ;(e.currentTarget as HTMLTextAreaElement).blur()
    }
  }

  const onRenameBlur = (e: FocusEvent) => {
    const target = e.currentTarget as HTMLTextAreaElement
    const name = target.value.trim()
    if (name) {
      renameNote(noteId(), name)
      mutate((prev) => prev ? { ...prev, title: name } : prev)
    }
    setRenaming(false)
  }

  const mode = () => noteMode()

  return (
    <div class="h-full flex flex-col">
      <div class="flex items-center justify-between px-4 py-2 shrink-0">
        <div class="flex-1 min-w-0 mr-2">
          <Show
            when={renaming()}
            fallback={
              <span
                class="text-[13px] text-[#9a9a9a] cursor-pointer hover:text-[#e0e0e0] transition-colors py-1.5"
                onClick={() => setRenaming(true)}
              >
                {note.loading ? "Loading..." : note()?.title ?? "Note"}
              </span>
            }
          >
            <textarea
              class="border border-white/20 px-2 py-1.5 text-[13px] bg-transparent text-[#e0e0e0] w-full resize-none outline-none overflow-hidden"
              rows={1}
              maxLength={120}
              onKeyDown={onRenameKeyDown}
              onBlur={onRenameBlur}
              onInput={(e) => adjustHeight(e.currentTarget)}
              ref={(el) => {
                if (el instanceof HTMLTextAreaElement) {
                  el.value = note()?.title ?? ""
                  requestAnimationFrame(() => {
                    el.focus()
                    el.setSelectionRange(el.value.length, el.value.length)
                    adjustHeight(el)
                  })
                }
              }}
            />
          </Show>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          {(["edit", "view"] as const).map((m) => (
            <button
              class={`border border-white/20 px-3 py-1.5 text-[13px] transition-colors cursor-pointer whitespace-nowrap ${
                mode() === m
                  ? "bg-white/10 text-[#e0e0e0]"
                  : "hover:bg-white/5 text-[#6a6a6a]"
              }`}
              onClick={() => { setNoteMode(m); saveConfig() }}
            >
              {m === "edit" ? "Edit Mode" : "View Mode"}
            </button>
          ))}
        </div>
      </div>

      <div class="flex-1 min-h-0 p-2">
        <Show
          when={note()}
          fallback={<div class="text-[#8b949e] px-4 py-3 text-[13px]">Loading note...</div>}
        >
          <Show
            when={mode() === "view"}
            fallback={
              <textarea
                class="w-full h-full bg-transparent border-0 px-4 py-3 text-[13px] text-[#e0e0e0] resize-none outline-none"
                placeholder="Write your notes here..."
                value={editContent()}
                onInput={(e) => onInput(e.currentTarget.value)}
              />
            }
          >
            <div class="px-4 py-3 chat-markdown overflow-y-auto h-full" style={{ "font-size": `${noteFontSize()}px` }}>
              <MarkdownView content={editContent()} />
            </div>
          </Show>
        </Show>
      </div>
    </div>
  )
}
