import { createEffect, onCleanup, onMount } from "solid-js"
import { parser, default_renderer, parser_write, parser_end } from "streaming-markdown"
import remend from "remend"
import DOMPurify from "dompurify"
import { marked } from "marked"
import hljs from "highlight.js/lib/core"

export default function StreamingMessage(props: { content: string; streaming: boolean }) {
  let containerEl!: HTMLDivElement
  let inst: ReturnType<typeof parser> | null = null

  onMount(() => {
    const renderer = default_renderer(containerEl)
    inst = parser(renderer)
    if (props.content) {
      parser_write(inst, remend(props.content))
    }
  })

  createEffect(() => {
    if (!inst || !props.streaming) return
    const text = props.content
    parser_write(inst, remend(text))
  })

  createEffect(() => {
    if (props.streaming || !inst) return
    parser_end(inst)
    containerEl.innerHTML = DOMPurify.sanitize(
      marked.parse(props.content, { async: false }),
      { ADD_ATTR: ["id"] },
    )
    // Re-highlight code blocks after innerHTML
    containerEl.querySelectorAll("pre code").forEach(b => {
      try { hljs.highlightElement(b as HTMLElement) } catch {}
    })
    inst = null
  })

  onCleanup(() => {
    if (inst) {
      try { parser_end(inst) } catch {}
      inst = null
    }
  })

  return <div ref={containerEl!} class="chat-markdown" />
}
