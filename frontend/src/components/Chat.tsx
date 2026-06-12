import { For, Show, createSignal, createEffect, createMemo, untrack } from "solid-js"
import { createVirtualizer } from "@tanstack/solid-virtual"
import "highlight.js/styles/github-dark.css"
import { currentMessages as messages, isStreaming, isThinking, currentToolStatus, currentChatError } from "../stores/chat-store"
import { activeSessionId } from "../stores/session-store"
import { chatFontSize } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import ContextMenu from "./ContextMenu"
import MarkdownView from "./MarkdownView"
import { copyToClipboard } from "../lib/clipboard"

export default function Chat(props: { viewportId?: string }) {
  let scrollRef!: HTMLDivElement
  const [expandedReasoning, setExpandedReasoning] = createSignal(new Set<number>())
  const [userScrolledUp, setUserScrolledUp] = createSignal(false)
  const [wasStreaming, setWasStreaming] = createSignal(false)

  const virtualizer = createVirtualizer({
    get count() { return messages().length },
    getScrollElement: () => scrollRef,
    // Size estimation by content length: with a fixed value, long messages
    // were sized too low and the scroll jumped on re-measure.
    // untrack: this runs inside solid-virtual's internal computed;
    // subscribing it to messages alters notification order relative to
    // mounted rows and leaves stale index accesses mid-cycle.
    estimateSize: (index: number) => untrack(() => {
      const len = messages()[index]?.content.length ?? 0
      return 40 + Math.ceil(len / 90) * 20
    }),
    overscan: 5,
    getItemKey: (index: number) => index,
  })

  createEffect(() => {
    const now = isStreaming()
    if (!wasStreaming() && now) {
      setUserScrolledUp(false)
    }
    setWasStreaming(now)
  })

  // scrollToIndex recalculates offsets of the entire list with estimated sizes
  // and "jumps" during streaming: reserved for landing on a session;
  // while the last message grows, direct scrollTop is enough (O(1) and smooth).
  let scrolledSession: string | null | undefined
  createEffect(() => {
    const msgs = messages()
    const sid = activeSessionId()
    const sessionChanged = sid !== scrolledSession
    scrolledSession = sid
    if (!userScrolledUp() && msgs.length > 0) {
      requestAnimationFrame(() => {
        if (sessionChanged) {
          virtualizer.scrollToIndex(msgs.length - 1, { align: "end" })
        } else if (scrollRef) {
          scrollRef.scrollTop = scrollRef.scrollHeight
        }
      })
    }
  })

  const onScroll = () => {
    const el = scrollRef
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
    setUserScrolledUp(!nearBottom)
  }

  // No need for virtualizer.measure() (invalidates ALL rows): the ref
  // measureElement installs a per-row ResizeObserver that re-measures only
  // the one that changes height when expanding/collapsing.
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

  return (
    <div ref={scrollRef} class="h-full overflow-y-auto overflow-anchor-none px-3 py-2" style={{ "font-size": `${chatFontSize()}px` }} onScroll={onScroll} onContextMenu={(e) => {
      if (e.target !== scrollRef) return
      e.preventDefault()
      setCtxMenu(null)
    }}>
      <div style={{ height: `${virtualizer.getTotalSize()}px`, width: "100%", position: "relative" }}>
        <For each={virtualizer.getVirtualItems()}>
          {(virtualRow) => {
            const msg = () => messages()[virtualRow.index]
            const i = () => virtualRow.index
            return (
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                data-index={virtualRow.index}
                ref={(el) => {
                  // The ref runs before Solid applies the JSX attribute;
                  // without data-index, measureElement aborts and the row
                  // stays without ResizeObserver (it would never re-measure).
                  el.setAttribute("data-index", String(virtualRow.index))
                  // Deferred: measuring here re-enters the virtualizer
                  // (notify → reconcile the source array) while For is still
                  // iterating, and undefined rows appear mid-mapping.
                  queueMicrotask(() => virtualizer.measureElement(el))
                }}
              >
                {/* msg() can be undefined for an instant when changing sessions
                    (virtual rows with previous session indices); without the
                    guard, TypeError breaks Solid's reactive graph. */}
                <Show when={msg()}>
                <div
                  class="mb-3"
                  classList={{ "flex justify-end": msg().role === "user" }}
                  onContextMenu={(e) => {
                    if (!msg().content) return
                    e.preventDefault()
                    e.stopPropagation()
                    setCtxMenu({
                      kind: "chat-message",
                      content: msg().content,
                      x: e.clientX,
                      y: e.clientY,
                    })
                  }}
                >
                  <div
                    classList={{
                      "border border-white/20 px-3 py-1.5 whitespace-pre-wrap break-words bg-white/5 max-w-[85%]":
                        msg().role === "user",
                      "py-1 chat-markdown w-full": msg().role === "assistant",
                    }}
                  >
                    <Show when={msg().role === "assistant" && msg().reasoning && !isThinking()}>
                      <div
                        class="thinking-block"
                        classList={{ "pb-2": !!msg().content }}
                      >
                        <div
                          class="thinking-toggle cursor-pointer"
                          onClick={() => toggleReasoning(i())}
                        >
                          {expandedReasoning().has(i()) ? "▼" : "▶"} Thinking
                        </div>
                        <Show when={expandedReasoning().has(i())}>
                          <div class="thinking-content whitespace-pre-wrap">
                            {msg().reasoning}
                          </div>
                        </Show>
                      </div>
                    </Show>

                    <Show when={msg().role === "assistant" && isThinking() && !msg().content && i() === messages().length - 1}>
                      <div class="thinking-block pb-1">
                        <div class="thinking-pending">Thinking...</div>
                      </div>
                    </Show>

                    {msg().role === "assistant" && !msg().content && isStreaming() && !isThinking() && i() === messages().length - 1
                      ? <span class="text-[#8b949e]">...</span>
                      : msg().role === "assistant"
                        ? <MarkdownView content={msg().content} streaming={isStreaming() && i() === messages().length - 1} />
                        : msg().content}

                    <Show when={msg().reportId && msg().reportTitle}>
                      <div
                        class="mt-2 border border-white/20 px-3 py-2 cursor-pointer hover:bg-white/5"
                        onClick={() => {
                          const vpId = props.viewportId
                          if (vpId) {
                            import("../stores/report-store").then((m) => m.openReportInViewport(vpId, msg().reportId!))
                          }
                        }}
                      >
                        <div class="text-[#e0e0e0] text-[13px]">{msg().reportTitle}</div>
                        <div class="flex justify-between text-[#6a6a6a] text-[11px] mt-1">
                          <span>Read full →</span>
                        </div>
                      </div>
                    </Show>
                  </div>
                </div>
                </Show>
              </div>
            )
          }}
        </For>
      </div>

      <Show when={currentToolStatus()}>
        {(s) => (
          <div class="thinking-block px-1 pb-1 sticky bottom-0" style="background: #000">
            <div class="thinking-pending">{s()}</div>
          </div>
        )}
      </Show>

      <Show when={currentChatError()}>
        {(err) => (
          <div class="mb-3 border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-2 text-[0.9em] whitespace-pre-wrap break-words">
            Agent error: {err()}
          </div>
        )}
      </Show>

      <Show when={messages().length === 0}>
        <div class="text-[#8b949e] flex items-center justify-center h-full">
          Ctrl+Enter in Write to send a message
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
  )
}
