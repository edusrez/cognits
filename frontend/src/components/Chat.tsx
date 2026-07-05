import { For, Show, createSignal, createEffect, createMemo, onMount, onCleanup } from "solid-js"
import "../highlight-theme.css"
import { currentMessages as messages, isStreaming, streamingContent, streamingReasoning, currentToolStatus, currentFavicons, currentChatError, type ChatMessage } from "../stores/chat-store"
import { activeSessionId, createNewSession } from "../stores/session-store"
import { chatFontSize, setChatFontSize, saveConfig, displayThinking, llmApiKey } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import { isSetupActive, setupStep } from "../stores/setup-store"
import ContextMenu from "./ContextMenu"
import StreamingMessage from "./StreamingMessage"
import { copyToClipboard } from "../lib/clipboard"

export default function Chat(props: { viewportId?: string }) {
  let scrollRef!: HTMLDivElement
  let anchorRef!: HTMLDivElement
  const [autoScroll, setAutoScroll] = createSignal(true)
  const [interviewStarted, setInterviewStarted] = createSignal(false)

  const chatMsgMenu = createMemo(() => {
    const m = ctxMenu()
    return m?.kind === "chat-message" ? m : null
  })

  onMount(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setAutoScroll(true)
      },
      { threshold: 0.1, root: scrollRef },
    )
    observer.observe(anchorRef)
    onCleanup(() => observer.disconnect())
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
        class="chat-scroller flex-1 overflow-y-auto overflow-x-hidden px-3 py-2"
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
          if (e.deltaY < 0) setAutoScroll(false)
        }}
        onTouchMove={() => setAutoScroll(false)}
      >
        <For each={messages()}>
          {(msg, idx) => (
            <div
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
                  ? <StreamingMessage content={msg.content} />
                  : msg.content}

                <Show when={msg.reports && msg.reports.length > 0}>
                  <For each={msg.reports}>
                    {report => (
                      <div
                        class="mt-2 border border-white/20 px-3 py-2 cursor-pointer hover:bg-white/5"
                        onClick={() => {
                          const vpId = props.viewportId
                          if (vpId) {
                            import("../stores/report-store").then(m => m.openReportInViewport(vpId, report.reportId))
                          }
                        }}
                      >
                        <div class="text-[#e0e0e0] text-[13px]">{report.reportTitle}</div>
                        <div class="flex justify-between text-[#6a6a6a] text-[11px] mt-1">
                          <span>Read full &rarr;</span>
                        </div>
                      </div>
                    )}
                  </For>
                </Show>
              </div>
            </div>
          )}
        </For>

        <Show when={isStreaming() && streamingContent()}>
          <div class="mb-3 py-1 w-full">
            <Show when={streamingReasoning() && displayThinking()}>
              <div class="thinking-block pb-2">
                <div class="thinking-content whitespace-pre-wrap">{streamingReasoning()}</div>
              </div>
            </Show>
            <StreamingMessage content={streamingContent()} streaming={true} />
          </div>
        </Show>

        <Show when={Object.keys(currentToolStatus()).length > 0}>
          <div
            style={{ "font-size": `${Math.max(10, chatFontSize() * 0.8)}px` }}
            class="text-[#5a5a5a] italic mt-1 flex flex-col gap-0.5"
          >
            <For each={Object.entries(currentToolStatus())}>
              {([agent, status]) => {
                const isAnimated = status.endsWith("...")
                const cleanStatus = isAnimated ? status.replace(/\.\.\.$/, "") : status
                const favicons = currentFavicons()[agent] ?? []
                return (
                  <div class="flex items-center gap-1.5">
                    <span class="inline-block min-w-[220px]" classList={{ "animate-dots": isAnimated }}>{agent}: {cleanStatus}</span>
                    <For each={favicons}>
                      {src => <img src={src} class="w-3.5 h-3.5 animate-fade-in" alt="" />}
                    </For>
                  </div>
                )
              }}
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

        <div ref={anchorRef!} class="chat-scroll-anchor" />

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
                      .filter((m: ChatMessage) => m.content)
                      .map((m: ChatMessage) => `**${m.role === "user" ? "User" : "Agent"}:** ${m.content}`)
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
          &darr; Scroll to bottom
        </button>
      </Show>
    </div>
  )
}
