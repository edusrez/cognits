import { createEffect, onCleanup, onMount } from "solid-js"
import { parser, default_renderer, parser_write, parser_end } from "streaming-markdown"
import remend from "remend"
import DOMPurify from "dompurify"
import { marked } from "marked"
import hljs from "highlight.js/lib/core"

export default function StreamingMessage(props: { content: string; streaming: boolean }) {
  let containerEl!: HTMLDivElement
  let inst: ReturnType<typeof parser> | null = null
  let lastLength = 0

  onMount(() => {
    if (!props.streaming) {
      containerEl.innerHTML = DOMPurify.sanitize(
        marked.parse(props.content, { async: false }),
        { ADD_ATTR: ["id"] },
      )
      containerEl.querySelectorAll("pre code").forEach(b => {
        try { hljs.highlightElement(b as HTMLElement) } catch {}
      })
      return
    }

    const renderer = default_renderer(containerEl)
    inst = parser(renderer)
    if (props.content) {
      const repaired = remend(props.content)
      lastLength = repaired.length
      parser_write(inst, repaired)
    }
  })

  createEffect(() => {
    if (!inst || !props.streaming) return
    const repaired = remend(props.content)
    if (repaired.length <= lastLength) return
    const delta = repaired.slice(lastLength)
    lastLength = repaired.length
    parser_write(inst, delta)
  })

  onCleanup(() => {
    if (inst) {
      try { parser_end(inst) } catch {}
      inst = null
    }
  })

  return <div ref={containerEl!} class="chat-markdown" />
}
