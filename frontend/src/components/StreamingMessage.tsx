import { createEffect, onCleanup, onMount } from "solid-js"
import { parser, default_renderer, parser_write, parser_end } from "streaming-markdown"
import DOMPurify from "dompurify"
import { marked } from "marked"
import hljs from "highlight.js/lib/core"
import { renderMarkdown } from "../lib/markdown"

export default function StreamingMessage(props: { content: string; streaming?: boolean }) {
  let containerEl!: HTMLDivElement
  let inst: ReturnType<typeof parser> | null = null
  let lastLength = 0

  onMount(() => {
    if (!props.streaming) {
      containerEl.innerHTML = renderMarkdown(props.content)
      containerEl.querySelectorAll("pre code").forEach(b => {
        try { hljs.highlightElement(b as HTMLElement) } catch {}
      })
      return
    }

    const renderer = default_renderer(containerEl)
    inst = parser(renderer)
    if (props.content) {
      lastLength = props.content.length
      parser_write(inst, props.content)
    }
  })

  createEffect(() => {
    if (!inst || !props.streaming) return
    const content = props.content
    if (content.length <= lastLength) return
    const delta = content.slice(lastLength)
    lastLength = content.length
    parser_write(inst, delta)
  })

  onCleanup(() => {
    if (inst) {
      try { parser_end(inst) } catch {}
      inst = null
    }
  })

  return <div ref={containerEl!} class="chat-markdown" classList={{ streaming: !!props.streaming }} />
}
