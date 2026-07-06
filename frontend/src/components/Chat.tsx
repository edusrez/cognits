import { For, Show, createSignal, createEffect, createMemo, onCleanup, on } from "solid-js"
import "../highlight-theme.css"
import { currentMessages as messages, isStreaming, streamingContent, streamingReasoning, toolEntries, turnId, currentChatError, scrollTick, agentLabelFor, type ChatMessage } from "../stores/chat-store"
import type { ToolEntry } from "../lib/sse-types"
import { activeSessionId, createNewSession } from "../stores/session-store"
import { chatFontSize, setChatFontSize, saveConfig, displayThinking, llmApiKey } from "../stores/settings-store"
import { ctxMenu, setCtxMenu } from "../stores/viewport-tree-store"
import { isSetupActive, setupStep } from "../stores/setup-store"
import ContextMenu from "./ContextMenu"
import StreamingMessage from "./StreamingMessage"
import { copyToClipboard } from "../lib/clipboard"

function squareClass(entry: ToolEntry): string {
  if (entry.done) return "shrink-0 inline-block w-2 h-2 border border-[#555] bg-[#cccccc] transition-colors duration-200"
  const msg = entry.message
  if (/error|fail/i.test(msg)) return "shrink-0 inline-block w-2 h-2 border border-[#e74c3c] bg-[#0d0d0d] transition-colors duration-200"
  return "shrink-0 inline-block w-2 h-2 border border-[#555] bg-[#0d0d0d] transition-colors duration-200"
}

function ToolEntryRow(props: { entry: ToolEntry; depth: number; childrenMap: Map<string, ToolEntry[]> }) {
  const label = () => agentLabelFor(props.entry.agent)
  const indent = () => `${props.depth * 20}px`

  let lastFavicons: string[] = []
  const uniqueFavicons = createMemo(
    on(() => props.entry.favicons, (favs) => {
      const seen = new Set<string>()
      const result = favs.filter(src => {
        if (!src || seen.has(src)) return false
        seen.add(src)
        return true
      })
      if (result.length === lastFavicons.length && result.every((src, i) => src === lastFavicons[i])) {
        return lastFavicons
      }
      lastFavicons = result
      return result
    })
  )

  return (
    <div class="flex flex-col">
      <div class="flex items-center gap-1.5 py-0.5" style={{ "padding-left": indent() }}>
        <span class={squareClass(props.entry)} />
        <span class="text-[#9a9a9a] truncate">
          {label()}
          <Show when={props.entry.message || (props.entry.done && props.entry.title)}>
            <Show when={props.entry.done && props.entry.title} fallback={
              <span class="text-[#6a6a6a]">: {props.entry.message!}</span>
            }>
              <span class="text-[#6a6a6a]">: {props.entry.title}</span>
            </Show>
          </Show>
        </span>
        <Show when={!props.entry.done && uniqueFavicons().length > 0}>
          <For each={uniqueFavicons()}>
            {(src) => (
              <img src={src} class="w-3.5 h-3.5" alt="" />
            )}
          </For>
        </Show>
      </div>
      <For each={props.childrenMap.get(props.entry.id) ?? []}>
        {child => (
          <ToolEntryRow
            entry={child}
            depth={props.depth + 1}
            childrenMap={props.childrenMap}
          />
        )}
      </For>
    </div>
  )
}

function ToolHistoryInline(props: { entries: ToolEntry[] }) {
  const [expanded, setExpanded] = createSignal(false)

  const topLevel = createMemo(() => props.entries.filter(e => e.parentId == null))
  const childrenMap = createMemo(() => {
    const map = new Map<string, ToolEntry[]>()
    for (const e of props.entries) {
      if (!e.parentId) continue
      const siblings = map.get(e.parentId) || []
      siblings.push(e)
      map.set(e.parentId, siblings)
    }
    return map
  })

  return (
    <div class="mt-1.5 text-[#5a5a5a]" style={{ "font-size": `${Math.max(10, chatFontSize() * 0.8)}px` }}>
      <div
        class="flex items-center gap-1.5 cursor-pointer select-none hover:text-[#e0e0e0]"
        onClick={() => setExpanded(!expanded())}
      >
        <span class="inline-block w-4">{expanded() ? "▾" : "▸"}</span>
        <span>{props.entries.length} tools used</span>
      </div>
      <Show when={expanded()}>
        <div class="flex flex-col gap-1 mt-0.5">
          <For each={topLevel()}>
            {entry => (
              <ToolEntryRow
                entry={entry}
                depth={0}
                childrenMap={childrenMap()}
              />
            )}
          </For>
        </div>
      </Show>
    </div>
  )
}

export default function Chat(props: { viewportId?: string }) {
  let scrollRef!: HTMLDivElement
  const [autoScroll, setAutoScroll] = createSignal(true)
  const [interviewStarted, setInterviewStarted] = createSignal(false)
  const [toolsCollapsed, setToolsCollapsed] = createSignal(false)
  const [autoCollapsed, setAutoCollapsed] = createSignal(false)
  const [userToggled, setUserToggled] = createSignal(false)

  let scrollVelocity = 0
  let scrollRafId: number | null = null
  const SCROLL_DAMPING = 0.7
  const SCROLL_STIFFNESS = 0.05
  const SCROLL_MASS = 1.25
  const BOTTOM_THRESHOLD = 70

  function springTick() {
    scrollRafId = null
    if (!autoScroll()) {
      scrollVelocity = 0
      return
    }
    const target = scrollRef.scrollHeight - scrollRef.clientHeight
    const current = scrollRef.scrollTop
    const diff = target - current
    if (diff > 0.5) {
      scrollVelocity = (SCROLL_DAMPING * scrollVelocity + SCROLL_STIFFNESS * diff) / SCROLL_MASS
      scrollRef.scrollTop = current + scrollVelocity
      scrollRafId = requestAnimationFrame(springTick)
    } else {
      if (diff > 0) scrollRef.scrollTop = target
      scrollVelocity = 0
    }
  }

  function kickSpring() {
    if (scrollRafId !== null) return
    scrollRafId = requestAnimationFrame(springTick)
  }

  onCleanup(() => {
    if (scrollRafId !== null) cancelAnimationFrame(scrollRafId)
  })

  const chatMsgMenu = createMemo(() => {
    const m = ctxMenu()
    return m?.kind === "chat-message" ? m : null
  })

  const topLevelEntries = createMemo(() => toolEntries().filter(e => e.parentId == null))

  const childrenByParentId = createMemo(() => {
    const map = new Map<string, ToolEntry[]>()
    for (const e of toolEntries()) {
      if (!e.parentId) continue
      const siblings = map.get(e.parentId) || []
      siblings.push(e)
      map.set(e.parentId, siblings)
    }
    return map
  })

  const toolSummary = createMemo(() => {
    const entries = toolEntries()
    if (entries.length === 0) return ""
    const running = entries.filter(e => !e.done)
    const runningAgents = [...new Set(running.map(e => agentLabelFor(e.agent)))]
    const firstAgent = runningAgents[0] ?? agentLabelFor(entries[0].agent)
    return `${entries.length} tools${running.length > 0 ? ` · ${firstAgent}...` : " · done"}`
  })


  createEffect(on(scrollTick, () => {
    setAutoScroll(true)
    kickSpring()
  }))

  createEffect(() => {
    const entries = toolEntries()
    if (entries.length > 0 && entries.every(e => e.done) && isStreaming() && streamingContent().length > 0) {
      setAutoCollapsed(true)
      if (!userToggled()) {
        setToolsCollapsed(true)
      }
    } else {
      setAutoCollapsed(false)
    }
  })

  createEffect(on(turnId, () => {
    setAutoCollapsed(false)
    setUserToggled(false)
    setToolsCollapsed(false)
  }))

  createEffect(() => {
    messages()
    streamingContent()
    toolEntries()  // scroll down when new tools appear/expand
    if (autoScroll()) kickSpring()
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
          if (e.deltaY < 0) {
            setAutoScroll(false)
          } else {
            const remaining = scrollRef.scrollHeight - scrollRef.scrollTop - scrollRef.clientHeight
            if (remaining < BOTTOM_THRESHOLD) setAutoScroll(true)
          }
        }}
        onTouchMove={() => {
          const remaining = scrollRef.scrollHeight - scrollRef.scrollTop - scrollRef.clientHeight
          if (remaining < BOTTOM_THRESHOLD) setAutoScroll(true)
          else setAutoScroll(false)
        }}
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

                <Show when={msg.role === "assistant" && msg.toolHistory && msg.toolHistory.length > 0}>
                  <ToolHistoryInline entries={msg.toolHistory!} />
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

        <Show when={toolEntries().length > 0}>
          <div
            style={{ "font-size": `${Math.max(10, chatFontSize() * 0.8)}px` }}
            class="text-[#5a5a5a] mt-1 flex flex-col gap-1"
          >
            <div
              class="flex items-center gap-1.5 cursor-pointer select-none hover:text-[#e0e0e0]"
              onClick={() => {
                setUserToggled(true)
                setToolsCollapsed(!toolsCollapsed())
              }}
            >
              <span class="inline-block w-4">{toolsCollapsed() ? "▸" : "▾"}</span>
              <span>{toolsCollapsed() ? toolSummary() : "Tools"}</span>
            </div>
            <Show when={!toolsCollapsed()}>
              <For each={topLevelEntries()}>
                {entry => (
                  <ToolEntryRow
                    entry={entry}
                    depth={0}
                    childrenMap={childrenByParentId()}
                  />
                )}
              </For>
            </Show>
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

        <Show when={messages().length === 0 && llmApiKey() && !isStreaming()}>
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
                      .filter((m: ChatMessage) => m.content)
                      .map((m: ChatMessage) => `**${m.role === "user" ? "User" : "Agent"}:** ${m.content}`)
                      .join("\n\n---\n\n")
                    copyToClipboard(md)
                  },
                },
                {
                  label: "Copy Conversation (DEBUG)",
                  onClick: () => {
                    setCtxMenu(null)
                    const md = messages()
                      .filter((m: ChatMessage) => m.content || m.reasoning || (m.toolHistory && m.toolHistory.length > 0) || (m.reports && m.reports.length > 0))
                      .map((m: ChatMessage) => {
                        const role = m.role === "user" ? "User" : m.role === "assistant" ? "Agent" : m.role === "hidden_user" ? "Hidden User" : "System"
                        let parts = [`**${role}:**`]
                        if (m.reasoning) parts.push(`\n[THINKING]\n${m.reasoning}`)
                        if (m.content) parts.push(`\n${m.content}`)
                        if (m.toolHistory && m.toolHistory.length > 0) {
                          parts.push(`\n[TOOLS]`)
                          for (const t of m.toolHistory) {
                            const status = t.done ? "✓" : "…"
                            const title = t.title ? `: ${t.title}` : t.message ? `: ${t.message}` : ""
                            parts.push(`${status} ${t.agent}${title}`)
                          }
                        }
                        if (m.reports && m.reports.length > 0) {
                          parts.push(`\n[REPORTS]`)
                          for (const r of m.reports) {
                            parts.push(`- ${r.reportTitle} (id: ${r.reportId})`)
                          }
                        }
                        return parts.join("\n")
                      })
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
          onClick={() => { setAutoScroll(true); kickSpring() }}
        >
          &darr; Scroll to bottom
        </button>
      </Show>
    </div>
  )
}
