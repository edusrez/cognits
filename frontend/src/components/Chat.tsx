import { For, Index, Show, createSignal, createEffect, createMemo, onMount, onCleanup } from "solid-js"
import "../highlight-theme.css"
import { currentMessages as messages, isStreaming, currentToolStatus, currentChatError, sessionUsage, mainSessionPromptTokens, toolFaviconsBySession } from "../stores/chat-store"
import { activeSessionId } from "../stores/session-store"
import { chatFontSize, setChatFontSize, saveConfig, displayThinking, llmApiKey } from "../stores/settings-store"
import { typewriterSpeed } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import ContextMenu from "./ContextMenu"
import MarkdownView from "./MarkdownView"
import { copyToClipboard } from "../lib/clipboard"
import { useTypewriter } from "../lib/useTypewriter"

export default function Chat(props: { viewportId?: string }) {
  let scrollRef!: HTMLDivElement
  const [autoScroll, setAutoScroll] = createSignal(true)

  const chatMsgMenu = createMemo(() => {
    const m = ctxMenu()
    if (m?.kind === "chat-message") return m
    return null
  })

  const animated = new Set<number>()

  const [displayedFavicons, setDisplayedFavicons] = createSignal<string[]>([])

  createEffect(() => {
    const sid = activeSessionId()
    if (!sid) return
    const target = toolFaviconsBySession()[sid] ?? []
    const current = displayedFavicons()

    if (target.length === 0) {
      setDisplayedFavicons([])
      return
    }

    // Compute new items that haven't been revealed yet
    const newItems = target.slice(current.length)
    if (newItems.length === 0) return

    let cancelled = false
    onCleanup(() => { cancelled = true })

    const reveal = async () => {
      for (const src of newItems) {
        if (cancelled) return
        await new Promise((r) => setTimeout(r, 200))
        if (cancelled) return
        setDisplayedFavicons((prev) => {
          // Only append if target still includes this src
          const latest = toolFaviconsBySession()[sid!] ?? []
          if (latest.length > prev.length) {
            return [...prev, src]
          }
          return prev
        })
      }
    }

    reveal()
  })

  createEffect(() => {
    if (!autoScroll()) return
    messages()
    scrollRef.scrollTop = scrollRef.scrollHeight
  })

  createEffect(() => {
    const msgs = messages()
    const last = msgs[msgs.length - 1]
    if (last && last.role === "assistant" && last.content === "") setAutoScroll(true)
  })

  return (
    <div class="flex flex-col h-full min-h-0 relative">
      <div
        ref={scrollRef}
        data-scrollable
        class="flex-1 overflow-y-auto px-3 py-2"
        style={{ "font-size": `${chatFontSize()}px` }}
        onContextMenu={(e) => {
          if (e.target !== scrollRef) return
          e.preventDefault()
          setCtxMenu(null)
        }}
        onWheel={(e) => {
          if (e.shiftKey) {
            e.preventDefault()
            const delta = e.deltaY > 0 ? -1 : 1
            setChatFontSize(Math.max(11, Math.min(24, chatFontSize() + delta)))
            saveConfig()
            return
          }
          setAutoScroll(false)
        }}
        onTouchMove={() => setAutoScroll(false)}
      >
      <Index each={messages()}>
        {(msg, idx) => {
          const i = () => idx
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
          const isLast = () => msg().role === "assistant" && isStreaming() && i() === messages().length - 1
          const typed = isLast() && sid ? useTypewriter(`${sid}-${i()}`, () => messages()[messages().length - 1].content, typewriterSpeed) : null
          return (
            <div
              ref={msgRef}
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
                <Show when={msg().role === "assistant" && msg().reasoning && !isStreaming() && displayThinking()}>
                  <div class="thinking-block pb-2">
                    <div class="thinking-content whitespace-pre-wrap">
                      {msg().reasoning}
                    </div>
                  </div>
                </Show>

                {msg().role === "assistant"
                  ? <MarkdownView content={typed ? typed() : msg().content} streaming={isStreaming() && i() === messages().length - 1} />
                  : msg().content}

                <Show when={msg().role === "assistant" && i() === messages().length - 1 && currentToolStatus()}>
                  <div
                    style={{ "font-size": `${Math.max(10, chatFontSize() * 0.8)}px` }}
                    class="text-[#5a5a5a] italic mt-1 flex items-center gap-1.5"
                  >
                    <span>{currentToolStatus()}</span>
                    <For each={displayedFavicons()}>
                      {(src) => (
                        <img src={src} class="w-3.5 h-3.5 animate-fade-in" alt="" />
                      )}
                    </For>
                  </div>
                </Show>

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
          )
        }}
      </Index>

      <Show when={currentChatError()}>
        {(err) => (
          <div class="mb-3 border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-2 text-[0.9em] whitespace-pre-wrap break-words">
            Agent error: {err()}
          </div>
        )}
      </Show>

      <Show when={!llmApiKey()}>
        <div class="text-[#8b949e] flex items-center justify-center h-full text-[0.9em]">
          Configure an API key in Settings before chatting.
        </div>
      </Show>

      <Show when={messages().length === 0 && llmApiKey()}>
        <div class="text-[#8b949e] flex items-center justify-center h-full">
          Type a message and press Enter to send
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
                label: "Copy Markdown",
                onClick: () => {
                  const text = m().content
                  setCtxMenu(null)
                  copyToClipboard(text)
                },
              },
              {
                label: "Copy Conversation",
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

      <Show when={!autoScroll() && messages().length > 0}>
        <button
          class="absolute bottom-3 left-1/2 -translate-x-1/2 bg-black border border-white/20 px-3 py-1.5 text-[13px] hover:bg-white/10 transition-colors cursor-pointer"
          onClick={() => {
            scrollRef.scrollTop = scrollRef.scrollHeight
            setAutoScroll(true)
          }}
        >
          &darr; Ir abajo
        </button>
      </Show>
    </div>
  )
}
