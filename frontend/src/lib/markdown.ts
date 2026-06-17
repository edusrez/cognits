import { Marked } from "marked"
import { markedHighlight } from "marked-highlight"
import hljs from "highlight.js/lib/core"
import javascript from "highlight.js/lib/languages/javascript"
import typescript from "highlight.js/lib/languages/typescript"
import python from "highlight.js/lib/languages/python"
import bash from "highlight.js/lib/languages/bash"
import go from "highlight.js/lib/languages/go"
import rust from "highlight.js/lib/languages/rust"
import css from "highlight.js/lib/languages/css"
import json from "highlight.js/lib/languages/json"
import sql from "highlight.js/lib/languages/sql"
import yaml from "highlight.js/lib/languages/yaml"
import xml from "highlight.js/lib/languages/xml"
import markdown from "highlight.js/lib/languages/markdown"
import diff from "highlight.js/lib/languages/diff"
import java from "highlight.js/lib/languages/java"
import c from "highlight.js/lib/languages/c"
import cpp from "highlight.js/lib/languages/cpp"
import ruby from "highlight.js/lib/languages/ruby"
import php from "highlight.js/lib/languages/php"
import swift from "highlight.js/lib/languages/swift"
import kotlin from "highlight.js/lib/languages/kotlin"
import ini from "highlight.js/lib/languages/ini"
import lua from "highlight.js/lib/languages/lua"
import r from "highlight.js/lib/languages/r"
import dart from "highlight.js/lib/languages/dart"
import erlang from "highlight.js/lib/languages/erlang"
import elixir from "highlight.js/lib/languages/elixir"
import haskell from "highlight.js/lib/languages/haskell"
import scala from "highlight.js/lib/languages/scala"
import clojure from "highlight.js/lib/languages/clojure"
import csharp from "highlight.js/lib/languages/csharp"
import graphql from "highlight.js/lib/languages/graphql"
import protobuf from "highlight.js/lib/languages/protobuf"
import remend from "remend"
import DOMPurify from "dompurify"

hljs.registerLanguage("javascript", javascript)
hljs.registerLanguage("js", javascript)
hljs.registerLanguage("typescript", typescript)
hljs.registerLanguage("ts", typescript)
hljs.registerLanguage("python", python)
hljs.registerLanguage("py", python)
hljs.registerLanguage("bash", bash)
hljs.registerLanguage("sh", bash)
hljs.registerLanguage("shell", bash)
hljs.registerLanguage("go", go)
hljs.registerLanguage("golang", go)
hljs.registerLanguage("rust", rust)
hljs.registerLanguage("rs", rust)
hljs.registerLanguage("css", css)
hljs.registerLanguage("json", json)
hljs.registerLanguage("sql", sql)
hljs.registerLanguage("yaml", yaml)
hljs.registerLanguage("yml", yaml)
hljs.registerLanguage("xml", xml)
hljs.registerLanguage("html", xml)
hljs.registerLanguage("markdown", markdown)
hljs.registerLanguage("md", markdown)
hljs.registerLanguage("diff", diff)
hljs.registerLanguage("java", java)
hljs.registerLanguage("c", c)
hljs.registerLanguage("cpp", cpp)
hljs.registerLanguage("c++", cpp)
hljs.registerLanguage("ruby", ruby)
hljs.registerLanguage("rb", ruby)
hljs.registerLanguage("php", php)
hljs.registerLanguage("swift", swift)
hljs.registerLanguage("kotlin", kotlin)
hljs.registerLanguage("ini", ini)
hljs.registerLanguage("toml", ini)
hljs.registerLanguage("lua", lua)
hljs.registerLanguage("r", r)
hljs.registerLanguage("dart", dart)
hljs.registerLanguage("erlang", erlang)
hljs.registerLanguage("elixir", elixir)
hljs.registerLanguage("haskell", haskell)
hljs.registerLanguage("scala", scala)
hljs.registerLanguage("clojure", clojure)
hljs.registerLanguage("csharp", csharp)
hljs.registerLanguage("cs", csharp)
hljs.registerLanguage("graphql", graphql)
hljs.registerLanguage("gql", graphql)
hljs.registerLanguage("protobuf", protobuf)
hljs.registerLanguage("proto", protobuf)

// Single Markdown configuration for the whole app: highlight + remend
// (incomplete markdown closure during streaming) + DOMPurify sanitization.
// All HTML derived from the web or LLM must go through here.
const marked = new Marked(
  markedHighlight({
    highlight(code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return escapeHtml(code)
    },
  }),
)

// marked v18 removed headerIds — generate them via custom renderer
marked.use({
  renderer: {
    heading({ tokens, depth }) {
      const raw = (this.parser as any).parseInline(tokens)
      const text = raw.replace(/<[^>]*>/g, "")
      const id = text.toLowerCase().replace(/[^\w]+/g, "-").replace(/^-|-$/g, "")
      return `<h${depth} id="${id}">${raw}</h${depth}>`
    },
  },
})

function escapeHtml(code: string): string {
  return code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

// Chat/report links open outside the app without losing state
// (it's an SPA) and without exposing window.opener to the target page.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.hasAttribute("href")) {
    const href = node.getAttribute("href")!
    if (!href.startsWith("#") && !href.startsWith("/")) {
      node.setAttribute("target", "_blank")
      node.setAttribute("rel", "noopener noreferrer")
    }
  }
})

// The virtualizer re-evaluates the markdown of all visible rows on every
// store update: without cache, each token would re-parse the entire chat.
const mdCache = new Map<string, string>()
const MD_CACHE_MAX = 300

export function renderMarkdown(text: string): string {
  const hit = mdCache.get(text)
  if (hit !== undefined) {
    mdCache.delete(text)
    mdCache.set(text, hit)
    return hit
  }
  const html = DOMPurify.sanitize(marked.parse(remend(text), { async: false }),
    { ADD_ATTR: ["id"] },
  )
  if (mdCache.size >= MD_CACHE_MAX) {
    mdCache.delete(mdCache.keys().next().value!)
  }
  mdCache.set(text, html)
  return html
}

// For the message that's growing: split off a stable prefix (always hits the
// cache) from the volatile tail, cutting at the last paragraph that doesn't
// fall inside a code fence. Cost per flush: O(last block).
// When the stream ends, a normal full render runs and the difference
// (e.g. a list split in two) disappears.
export function renderMarkdownStreaming(text: string): string {
  let idx = text.lastIndexOf("\n\n")
  while (idx > 0) {
    const prefix = text.slice(0, idx)
    const fences = (prefix.match(/```/g) ?? []).length
    if (fences % 2 === 0) {
      return renderMarkdown(prefix) + renderMarkdown(text.slice(idx))
    }
    idx = text.lastIndexOf("\n\n", idx - 1)
  }
  return renderMarkdown(text)
}

// For FTS search highlighted titles: only highlight markup (<b>/<mark>) is
// allowed; everything else is stripped.
export function sanitizeHighlight(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ["b", "mark"], ALLOWED_ATTR: [] })
}

export function highlightCode(code: string, language: string): string {
  if (language && hljs.getLanguage(language)) {
    return hljs.highlight(code, { language }).value
  }
  return escapeHtml(code)
}

export function escapeHtmlSafe(text: string): string {
  return escapeHtml(text)
}
