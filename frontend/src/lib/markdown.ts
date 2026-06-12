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

// Configuración única de Markdown para toda la app: highlight + remend
// (cierre de markdown incompleto durante streaming) + sanitizado DOMPurify.
// Todo HTML derivado de la web o del LLM debe pasar por aquí.
const marked = new Marked(
  markedHighlight({
    highlight(code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      // Sin lenguaje declarado no se resalta: highlightAuto prueba ~20
      // lexers por bloque y en streaming se ejecutaba en cada re-parseo.
      // marked-highlight inserta el retorno tal cual, así que hay que escapar.
      return escapeHtml(code)
    },
  }),
)

function escapeHtml(code: string): string {
  return code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

// Los enlaces del chat/informes abren fuera de la app sin perder el estado
// (es una SPA) y sin ceder window.opener a la página destino.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank")
    node.setAttribute("rel", "noopener noreferrer")
  }
})

// El virtualizador re-evalúa el markdown de todas las filas visibles en cada
// actualización del store: sin caché, cada token re-parseaba todo el chat.
const mdCache = new Map<string, string>()
const MD_CACHE_MAX = 300

export function renderMarkdown(text: string): string {
  const hit = mdCache.get(text)
  if (hit !== undefined) {
    mdCache.delete(text)
    mdCache.set(text, hit)
    return hit
  }
  const html = DOMPurify.sanitize(marked.parse(remend(text), { async: false }))
  if (mdCache.size >= MD_CACHE_MAX) {
    mdCache.delete(mdCache.keys().next().value!)
  }
  mdCache.set(text, html)
  return html
}

// Para el mensaje que está creciendo: separa un prefijo estable (que acierta
// siempre en la caché) de la cola volátil, cortando por el último párrafo que
// no caiga dentro de un code fence. Coste por flush: O(último bloque).
// Al terminar el stream se hace un render completo normal y la diferencia
// (p.ej. una lista partida en dos) desaparece.
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

// Para los títulos resaltados de la búsqueda FTS: solo se permite el marcado
// del highlight (<b>/<mark>), el resto se elimina.
export function sanitizeHighlight(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ["b", "mark"], ALLOWED_ATTR: [] })
}
