import { For, Show, createSignal, createEffect, createMemo, onMount } from "solid-js"
import "highlight.js/styles/github-dark.css"
import { currentMessages as messages, isStreaming, isThinking, currentToolStatus, currentChatError, sessionUsage, mainSessionPromptTokens } from "../stores/chat-store"
import { activeSessionId } from "../stores/session-store"
import { chatFontSize } from "../stores/settings-store"
import { typewriterSpeed } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import ContextMenu from "./ContextMenu"
import MarkdownView from "./MarkdownView"
import { copyToClipboard } from "../lib/clipboard"
import { useTypewriter } from "../lib/useTypewriter"

export default function Chat(props: { viewportId?: string }) {
  let scrollRef!: HTMLDivElement
  const [expandedReasoning, setExpandedReasoning] = createSignal(new Set<number>())
  const [isSticky, setIsSticky] = createSignal(true)
  const [wasStreaming, setWasStreaming] = createSignal(false)

  const onScroll = () => {
    const el = scrollRef
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    setIsSticky(atBottom)
  }

  // Scroll to bottom on new messages when user hasn't scrolled up.
  createEffect(() => {
    messages()
    if (isSticky()) {
      requestAnimationFrame(() => {
        scrollRef.scrollTop = scrollRef.scrollHeight
      })
    }
  })

  // When streaming starts, re-pin to bottom so the user sees the response.
  createEffect(() => {
    const now = isStreaming()
    if (!wasStreaming() && now) setIsSticky(true)
    setWasStreaming(now)
  })

  // Scroll to bottom on session change.
  let scrolledSession: string | null | undefined
  createEffect(() => {
    const sid = activeSessionId()
    if (sid !== scrolledSession) {
      scrolledSession = sid
      setIsSticky(true)
      requestAnimationFrame(() => {
        scrollRef.scrollTop = scrollRef.scrollHeight
      })
    }
  })

  const toggleReasoning = (idx: number) => {
    setExpandedReasoning((prev) => {
      const next = new Set(prev)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  const chatMsgMenu = createMemo(() => {
    const m = ctxMenu()
    if (m?.kind === "chat-message") return m
    return null
  })

  const animated = new Set<number>()

  return (
    <div class="flex flex-col h-full">
      <div
        ref={scrollRef}
        data-scrollable
        class="flex-1 overflow-y-auto px-3 py-2"
        style={{ "font-size": `${chatFontSize()}px` }}
        onScroll={onScroll}
        onContextMenu={(e) => {
          if (e.target !== scrollRef) return
          e.preventDefault()
          setCtxMenu(null)
        }}
      >
      <For each={messages()}>
        {(msg, idx) => {
          const i = () => idx()
          let msgRef!: HTMLDivElement
          if (!animated.has(i())) {
            animated.add(i())
            onMount(() => {
              msgRef.animate(
                [
                  { opacity: 0, transform: "translateY(8px)" },
                  { opacity: 1, transform: "translateY(0)" },
                ],
                { duration: 200, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "both" },
              )
            })
          }
          const sid = activeSessionId()
          const isLast = () => msg.role === "assistant" && isStreaming() && i() === messages().length - 1 && !!msg.content
          const typed = isLast() && sid ? useTypewriter(`${sid}-${i()}`, () => messages()[messages().length - 1].content, typewriterSpeed) : null
          return (
            <div
              ref={msgRef}
              class="mb-3"
              classList={{ "flex justify-end": msg.role === "user" }}
              onContextMenu={(e) => {
                if (!msg.content) return
                e.preventDefault()
                e.stopPropagation()
                setCtxMenu({
                  kind: "chat-message",
                  content: msg.content,
                  x: e.clientX,
                  y: e.clientY,
                })
              }}
            >
              <div
                classList={{
                  "border border-white/20 px-3 py-1.5 whitespace-pre-wrap break-words bg-white/5 max-w-[85%]":
                    msg.role === "user",
                  "py-1 chat-markdown w-full": msg.role === "assistant",
                }}
              >
                <Show when={msg.role === "assistant" && msg.reasoning && !isThinking()}>
                  <div
                    class="thinking-block"
                    classList={{ "pb-2": !!msg.content }}
                  >
                    <div
                      class="thinking-toggle cursor-pointer"
                      onClick={() => toggleReasoning(i())}
                    >
                      {expandedReasoning().has(i()) ? "\u25BC" : "\u25B6"} Thinking
                    </div>
                    <Show when={expandedReasoning().has(i())}>
                      <div class="thinking-content whitespace-pre-wrap">
                        {msg.reasoning}
                      </div>
                    </Show>
                  </div>
                </Show>

                <Show when={msg.role === "assistant" && isThinking() && !msg.content && i() === messages().length - 1}>
                  <div class="thinking-block pb-1">
                    <div class="thinking-pending">Thinking...</div>
                  </div>
                </Show>

                {msg.role === "assistant" && !msg.content && isStreaming() && !isThinking() && i() === messages().length - 1
                  ? <span class="text-[#8b949e]">...</span>
                  : msg.role === "assistant"
                    ? <MarkdownView content={typed ? typed() : msg.content} streaming={isStreaming() && i() === messages().length - 1} />
                    : msg.content}

                <Show when={msg.reportId && msg.reportTitle}>
                  <div
                    class="mt-2 border border-white/20 px-3 py-2 cursor-pointer hover:bg-white/5"
                    onClick={() => {
                      const vpId = props.viewportId
                      if (vpId) {
                        import("../stores/report-store").then((m) => m.openReportInViewport(vpId, msg.reportId!))
                      }
                    }}
                  >
                    <div class="text-[#e0e0e0] text-[13px]">{msg.reportTitle}</div>
                    <div class="flex justify-between text-[#6a6a6a] text-[11px] mt-1">
                      <span>Read full →</span>
                    </div>
                  </div>
                </Show>
              </div>
            </div>
          )
        }}
      </For>

      <Show when={currentChatError()}>
        {(err) => (
          <div class="mb-3 border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-2 text-[0.9em] whitespace-pre-wrap break-words">
            Agent error: {err()}
          </div>
        )}
      </Show>

      <Show when={messages().length === 0}>
        <div class="text-[#8b949e] flex items-center justify-center h-full">
          Type a message and press Enter to send
        </div>
      </Show>

      <Show when={messages().length > 0 && !isSticky()}>
        <div class="sticky bottom-2 flex justify-center">
          <button
            class="border border-white/20 bg-black/80 hover:bg-white/10 transition-colors cursor-pointer px-4 py-1.5 text-[13px] text-[#9a9a9a]"
            onClick={() => {
              setIsSticky(true)
              scrollRef.scrollTop = scrollRef.scrollHeight
            }}
          >
            ↓ Ir abajo
          </button>
        </div>
      </Show>

      <Show when={chatMsgMenu()}>
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
              {
                label: "Copy Conversation in Markdown",
                onClick: () => {
                  setCtxMenu(null)
                  const md = messages()
                    .filter((msg) => msg.content)
                    .map((m) => `**${m.role === "user" ? "User" : "Agent"}:** ${m.content}`)
                    .join("\n\n---\n\n")
                  copyToClipboard(md)
                },
              },
            ]}
          />
        )}
      </Show>
      </div>
    </div>
  )
}
