import { For, onMount, createSignal, Show, createMemo } from "solid-js"
import {
  sessions,
  activeSessionId,
  setActiveSessionId,
  loadSessions,
  createNewSession,
  isCreatingSession,
  renameSession,
  deleteSession,
  type Session,
} from "../stores/session-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import { listDragState, initiateListDrag, moveHint } from "../drag/drag-state"
import ContextMenu from "./ContextMenu"

export default function Sessions() {
  onMount(() => {
    loadSessions()
  })

  const [renaming, setRenaming] = createSignal<string | null>(null)

  const onContextMenu = (e: MouseEvent, session: Session) => {
    e.preventDefault()
    e.stopPropagation()
    setCtxMenu({ kind: "session", sessionId: session.id, x: e.clientX, y: e.clientY })
  }

  const sessionMenu = createMemo(() => {
    const m = ctxMenu()
    if (m?.kind === "session") return m
    return null
  })

  const startRenaming = () => {
    const m = ctxMenu()
    if (m?.kind === "session") {
      setRenaming(m.sessionId)
      setCtxMenu(null)
    }
  }

  const handleDelete = () => {
    const m = ctxMenu()
    if (m?.kind === "session") {
      deleteSession(m.sessionId)
      setCtxMenu(null)
    }
  }

  // Enter only removes focus; the single save happens on blur (avoids two PUTs).
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
      renameSession(id, name)
    }
    setRenaming(null)
  }

  const adjustHeight = (el: HTMLTextAreaElement) => {
    el.style.height = "auto"
    el.style.height = el.scrollHeight + "px"
  }

  const ds = () => listDragState()

  const displaySessions = createMemo(() => {
    const all = sessions()
    const mh = moveHint()
    if (mh && mh.listId === "sessions") {
      const filtered = all.filter((s) => s.id !== mh.itemId)
      const idx = Math.min(mh.targetIndex, filtered.length)
      const item = all.find((s) => s.id === mh.itemId)
      const ghost: Session = { id: "__ghost__", name: item?.name ?? "", createdAt: "" }
      return [...filtered.slice(0, idx), ghost, ...filtered.slice(idx)]
    }
    if (!ds().isDragging || ds().listId !== "sessions") return all
    const filtered = all.filter((s) => s.id !== ds().itemId)
    const idx = Math.min(ds().insertIndex >= 0 ? ds().insertIndex : filtered.length, filtered.length)
    const ghost: Session = { id: "__ghost__", name: ds().itemLabel, createdAt: "" }
    return [...filtered.slice(0, idx), ghost, ...filtered.slice(idx)]
  })

  const onSessionMouseDown = (session: Session, e: MouseEvent) => {
    initiateListDrag(session.id, session.name, "sessions", e)
  }

  return (
    <div class="p-2 flex flex-col gap-2" data-list-id="sessions">
      <button
        class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors w-full text-left cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        disabled={isCreatingSession()}
        onClick={(e) => {
          e.stopPropagation()
          createNewSession()
        }}
      >
        + Create Session
      </button>

      <For each={displaySessions()}>
        {(item) => (
          <Show
            when={item.id === "__ghost__"}
            fallback={
              <Show
                when={renaming() === item.id}
                fallback={
                  <button
                    data-session-id={item.id}
                    data-drag-item=""
                    class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors w-full text-left whitespace-pre-wrap cursor-pointer"
                    classList={{
                      "bg-white/10": activeSessionId() === item.id && item.id !== "__ghost__",
                      "list-drag-dimmed": ds().isDragging && ds().listId === "sessions" && item.id !== ds().itemId,
                    }}
                    onMouseDown={(e) => onSessionMouseDown(item, e)}
                    onClick={() => {
                      if (ds().isDragging) return
                      setActiveSessionId(activeSessionId() === item.id ? null : item.id)
                    }}
                    onContextMenu={(e) => onContextMenu(e, item)}
                  >
                    {item.name}
                  </button>
                }
              >
                <textarea
                  data-drag-item=""
                  class="border border-white/20 px-3 py-1.5 text-[13px] bg-transparent text-[#e0e0e0] w-full resize-none outline-none overflow-hidden"
                  classList={{
                    "list-drag-dimmed": ds().isDragging && ds().listId === "sessions" && item.id !== ds().itemId,
                  }}
                  rows={1}
                  maxLength={120}
                  onKeyDown={onRenameKeyDown}
                  onBlur={(e) => onRenameBlur(e, item.id)}
                  onInput={(e) => adjustHeight(e.currentTarget)}
                  ref={(el) => {
                    if (el instanceof HTMLTextAreaElement) {
                      el.value = item.name
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
              {item.name}
            </div>
          </Show>
        )}
      </For>

      <Show when={sessionMenu()}>
        {(m) => (
          <ContextMenu
            x={m().x}
            y={m().y}
            onClose={() => setCtxMenu(null)}
            items={[
              { label: "Rename", onClick: startRenaming },
              { label: "Delete", onClick: handleDelete, class: "text-red-400" },
            ]}
          />
        )}
      </Show>
    </div>
  )
}
