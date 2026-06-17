import { createMemo } from "solid-js"
import { renderMarkdown, renderMarkdownStreaming } from "../lib/markdown"

export default function MarkdownView(props: { content: string; streaming?: boolean }) {
  const html = createMemo(() =>
    props.streaming ? renderMarkdownStreaming(props.content) : renderMarkdown(props.content),
  )

  function onClick(e: MouseEvent) {
    const anchor = (e.target as HTMLElement).closest("a[href^='#']")
    if (!anchor) return
    e.preventDefault()
    const id = (anchor as HTMLAnchorElement).getAttribute("href")!.slice(1)
    const target = document.getElementById(id)
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return <div innerHTML={html()} onClick={onClick} />
}
