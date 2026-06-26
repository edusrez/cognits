import { For, Show, createSignal, createEffect, createMemo, onMount } from "solid-js"
import "../highlight-theme.css"
import { currentMessages as messages, isStreaming, streamingContent, currentToolStatus, currentChatError, toolFavicons, type ChatMessage } from "../stores/chat-store"
import { activeSessionId, createNewSession } from "../stores/session-store"
import { chatFontSize, setChatFontSize, saveConfig, displayThinking, llmApiKey } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import { isSetupActive, setupStep } from "../stores/setup-store"
import ContextMenu from "./ContextMenu"
import StreamingMessage from "./StreamingMessage"
import { copyToClipboard } from "../lib/clipboard"

const animatedKeys = new Set<string>()

export default function Chat(props: { viewportId?: string }) {
  let scrollRef!: HTMLDivElement
  const [autoScroll, setAutoScroll] = createSignal(true)
  const [interviewStarted, setInterviewStarted] = createSignal(false)
  const [displayedFavicons, setDisplayedFavicons] = createSignal<string[]>([])

  const syntheticMsg: ChatMessage = { role: "assistant", content: "" }

  const displayedMessages = createMemo(() => {
    const msgs = messages()
    if (!isStreaming()) return msgs
    syntheticMsg.content = streamingContent()
    return [...msgs, syntheticMsg]
  })

  const chatMsgMenu = createMemo(() => {
    const m = ctxMenu()
    return m?.kind === "chat-message" ? m : null
  })

  createEffect(() => {
    const sid = activeSessionId()
    if (!sid) return
    const target = toolFavicons() ?? []
    const current = displayedFavicons()
    if (target.length === 0) { setDisplayedFavicons([]); return }
    const newItems = target.slice(current.length)
    if (newItems.length === 0) return
    let cancelled = false
    const reveal = async () => {
      for (const src of newItems) {
        if (cancelled) return
        await new Promise(r => setTimeout(r, 200))
        if (cancelled) return
        setDisplayedFavicons(prev => {
          const latest = toolFavicons() ?? []
          return latest.length > prev.length ? [...prev, src] : prev
        })
      }
    }
    reveal()
  })

  createEffect(() => {
    if (!autoScroll()) return
    messages()
    streamingContent()
    scrollRef.scrollTop = scrollRef.scrollHeight
  })

  createEffect(() => {
    if (
      isSetupActive() &&
      setupStep() === "onboarding" &&
      !activeSessionId() &&
      !interviewStarted()
    ) {
      setInterviewStarted(true)
      createNewSession()
    }
  })

  return (
    <div class="flex flex-col h-full min-h-0 relative">
      <div
        ref={scrollRef}
        data-scrollable
        class="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2"
        style={{ "font-size": `${chatFontSize()}px` }}
        onContextMenu={e => {
          if (e.target !== scrollRef) return
          e.preventDefault()
          setCtxMenu(null)
        }}
        onWheel={e => {
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
      <For each={displayedMessages()}>
        {(msg, idx) => {
          let msgRef!: HTMLDivElement
          const isLast = () => !isStreaming() && idx() === displayedMessages().length - 1
          const isStreamingMsg = () => isStreaming() && idx() === displayedMessages().length - 1

          onMount(() => {
            if (isStreamingMsg()) return
            const key = `${msg.role}|${msg.content.slice(0, 80)}`
            if (animatedKeys.has(key)) return
            animatedKeys.add(key)
            msgRef.animate(
              [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }],
              { duration: 200, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "both" },
            )
          })

          return (
            <div
              ref={msgRef}
              class="mb-3"
              classList={{ "flex justify-end": msg.role === "user" }}
              onContextMenu={e => {
                if (!msg.content) return
                e.preventDefault()
                e.stopPropagation()
                setCtxMenu({ kind: "chat-message", content: msg.content, x: e.clientX, y: e.clientY })
              }}
            >
              <div
                classList={{
                  "border border-white/20 px-3 py-1.5 whitespace-pre-wrap break-words bg-white/5 max-w-[85%]": msg.role === "user",
                  "py-1 w-full": msg.role === "assistant",
                }}
              >
                <Show when={msg.role === "assistant" && msg.reasoning && displayThinking()}>
                  <div class="thinking-block pb-2">
                    <div class="thinking-content whitespace-pre-wrap">{msg.reasoning}</div>
                  </div>
                </Show>

                {msg.role === "assistant"
                  ? <StreamingMessage content={msg.content} streaming={isStreamingMsg()} />
                  : msg.content}

                <Show when={msg.reportId && msg.reportTitle}>
                  <div
                    class="mt-2 border border-white/20 px-3 py-2 cursor-pointer hover:bg-white/5"
                    onClick={() => {
                      const vpId = props.viewportId
                      if (vpId) {
                        import("../stores/report-store").then(m => m.openReportInViewport(vpId, msg.reportId!))
                      }
                    }}
                  >
                    <div class="text-[#e0e0e0] text-[13px]">{msg.reportTitle}</div>
                    <div class="flex justify-between text-[#6a6a6a] text-[11px] mt-1">
                      <span>Read full &rarr;</span>
                    </div>
                  </div>
                </Show>
              </div>
            </div>
          )
        }}
      </For>

      <Show when={currentToolStatus()}>
        <div
          style={{ "font-size": `${Math.max(10, chatFontSize() * 0.8)}px` }}
          class="text-[#5a5a5a] italic mt-1 flex items-center gap-1.5"
        >
          <span>{currentToolStatus()}</span>
          <For each={displayedFavicons()}>
            {src => <img src={src} class="w-3.5 h-3.5 animate-fade-in" alt="" />}
          </For>
        </div>
      </Show>

      <Show when={currentChatError()}>
        {err => (
          <div class="mb-3 border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-2 text-[0.9em] whitespace-pre-wrap break-words">
            Agent error: {err()}
          </div>
        )}
      </Show>

      <Show when={messages().length === 0 && !llmApiKey() && !isSetupActive()}>
        <div class="text-[#8b949e] text-center text-[0.9em]">
          Configure an API key in Settings before chatting.
        </div>
      </Show>

      <Show when={messages().length === 0 && llmApiKey()}>
        <div class="text-[#8b949e] flex items-center justify-center h-full">
          Type a message and press Enter to send
        </div>
      </Show>

      <Show when={chatMsgMenu()}>
        {m => (
          <ContextMenu
            x={m().x}
            y={m().y}
            onClose={() => setCtxMenu(null)}
            items={[
              {
                label: "Copy Markdown",
                onClick: () => { setCtxMenu(null); copyToClipboard(m().content) },
              },
              {
                label: "Copy Conversation",
                onClick: () => {
                  setCtxMenu(null)
                  const md = messages()
                    .filter(m => m.content)
                    .map(m => `**${m.role === "user" ? "User" : "Agent"}:** ${m.content}`)
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
          onClick={() => { scrollRef.scrollTop = scrollRef.scrollHeight; setAutoScroll(true) }}
        >
          &darr; Ir abajo
        </button>
      </Show>
    </div>
  )
}
