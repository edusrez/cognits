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

  return (
    <div class="p-2 flex flex-col gap-2">
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

      <For each={sessions()}>
        {(session) => (
          <Show
            when={renaming() === session.id}
            fallback={
              <button
                data-session-id={session.id}
                class="border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors w-full text-left whitespace-pre-wrap cursor-pointer"
                classList={{
                  "bg-white/10": activeSessionId() === session.id,
                }}
                onClick={(e) => {
                  e.stopPropagation()
                  setActiveSessionId(session.id)
                }}
                onContextMenu={(e) => onContextMenu(e, session)}
              >
                {session.name}
              </button>
            }
          >
            <textarea
              class="border border-white/20 px-3 py-1.5 text-[13px] bg-transparent text-[#e0e0e0] w-full resize-none outline-none overflow-hidden"
              rows={1}
              maxLength={120}
              onKeyDown={onRenameKeyDown}
              onBlur={(e) => onRenameBlur(e, session.id)}
              onInput={(e) => adjustHeight(e.currentTarget)}
              ref={(el) => {
                if (el instanceof HTMLTextAreaElement) {
                  el.value = session.name
                  requestAnimationFrame(() => {
                    el.focus()
                    el.setSelectionRange(el.value.length, el.value.length)
                    adjustHeight(el)
                  })
                }
              }}
            />
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
