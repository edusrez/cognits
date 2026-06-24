import { parser, default_renderer, parser_write, parser_end } from "streaming-markdown"
import { createEffect, onCleanup, onMount } from "solid-js"

export default function StreamingMarkdown(props: { content: string }) {
  let container!: HTMLDivElement
  let inst: ReturnType<typeof parser>
  let lastLength = 0

  onMount(() => {
    const renderer = default_renderer(container)
    inst = parser(renderer)
    parser_write(inst, props.content)
    onCleanup(() => { try { parser_end(inst) } catch {} })
  })

  createEffect(() => {
    const text = props.content
    if (text.length > lastLength) {
      parser_write(inst, text.slice(lastLength))
      lastLength = text.length
    }
  })

  return <div ref={container} />
}
