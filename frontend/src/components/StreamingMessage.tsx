import { createEffect, onCleanup, onMount } from "solid-js"
import { parser, default_renderer, parser_write, parser_end } from "streaming-markdown"
import hljs from "highlight.js/lib/core"

export default function StreamingMessage(props: { content: string; streaming?: boolean }) {
  let containerEl!: HTMLDivElement
  let inst: ReturnType<typeof parser> | null = null
  let lastLength = 0

  onMount(() => {
    const renderer = default_renderer(containerEl)
    inst = parser(renderer)

    if (props.streaming) {
      if (props.content) {
        lastLength = props.content.length
        parser_write(inst, props.content)
      }
    } else {
      if (props.content) {
        parser_write(inst, props.content)
      }
      parser_end(inst)
      containerEl.querySelectorAll("pre code").forEach(b => {
        try { hljs.highlightElement(b as HTMLElement) } catch {}
      })
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
