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
    // Estimación por longitud del contenido: con un valor fijo los mensajes
    // largos se median muy por debajo y el scroll saltaba al re-medirlos.
    // untrack: esto se ejecuta dentro del computed interno de solid-virtual;
    // suscribirlo a messages altera el orden de notificación frente a las
    // filas montadas y deja accesos con índices obsoletos a mitad de ciclo.
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

  // scrollToIndex re-calcula offsets de toda la lista con tamaños estimados y
  // "salta" durante el streaming: se reserva para el aterrizaje en una sesión;
  // mientras crece el último mensaje basta scrollTop directo (O(1) y suave).
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

  // No hace falta virtualizer.measure() (invalida TODAS las filas): el ref
  // measureElement instala un ResizeObserver por fila que re-mide solo la
  // que cambia de altura al expandir/plegar.
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
                  // El ref corre antes de que Solid aplique el atributo JSX;
                  // sin data-index, measureElement aborta y la fila se queda
                  // sin ResizeObserver (no se re-mediría nunca).
                  el.setAttribute("data-index", String(virtualRow.index))
                  // Diferido: medir aquí mismo re-entra en el virtualizador
                  // (notify → reconcile del array fuente) mientras el For aún
                  // está iterando, y aparecen filas undefined a mitad de mapeo.
                  queueMicrotask(() => virtualizer.measureElement(el))
                }}
              >
                {/* msg() puede ser undefined un instante al cambiar de sesión
                    (filas virtuales con índices de la sesión anterior); sin el
                    guard, el TypeError rompe el grafo reactivo de Solid. */}
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
                          {expandedReasoning().has(i()) ? "▼" : "▶"} Pensamiento
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
                        <div class="thinking-pending">Pensando...</div>
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
                          <span>Leer completo →</span>
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
            Error del agente: {err()}
          </div>
        )}
      </Show>

      <Show when={messages().length === 0}>
        <div class="text-[#8b949e] flex items-center justify-center h-full">
          Ctrl+Enter en Escribir para enviar un mensaje
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
                label: "Copiar en Markdown",
                onClick: () => {
                  const text = m().content
                  setCtxMenu(null)
                  copyToClipboard(text)
                },
              },
              {
                label: "Copiar Conversación en Markdown",
                onClick: () => {
                  setCtxMenu(null)
                  const md = messages()
                    .filter((msg) => msg.content)
                    .map((m) => `**${m.role === "user" ? "Usuario" : "Agente"}:** ${m.content}`)
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
