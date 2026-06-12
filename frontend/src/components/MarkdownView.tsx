import { createMemo } from "solid-js"
import { renderMarkdown, renderMarkdownStreaming } from "../lib/markdown"

// Único punto de inserción de HTML derivado de markdown: memoiza por contenido
// y elige el render incremental mientras el mensaje sigue creciendo.
export default function MarkdownView(props: { content: string; streaming?: boolean }) {
  const html = createMemo(() =>
    props.streaming ? renderMarkdownStreaming(props.content) : renderMarkdown(props.content),
  )
  return <div innerHTML={html()} />
}
