import { createMemo } from "solid-js"
import { renderMarkdown, renderMarkdownStreaming } from "../lib/markdown"

// Single insertion point for HTML derived from markdown: memoizes by content
// and chooses incremental rendering while the message is still growing.
export default function MarkdownView(props: { content: string; streaming?: boolean }) {
  const html = createMemo(() =>
    props.streaming ? renderMarkdownStreaming(props.content) : renderMarkdown(props.content),
  )
  return <div innerHTML={html()} />
}
