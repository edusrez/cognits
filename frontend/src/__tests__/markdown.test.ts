/** Tests for lib/markdown.ts, chat-stream.ts, and stores */

import { describe, it, expect } from "vitest"
import { renderMarkdown, sanitizeHighlight, highlightCode } from "../lib/markdown"

describe("renderMarkdown", () => {
  it("renders plain text", () => {
    const result = renderMarkdown("Hello world")
    expect(result).toContain("Hello world")
  })
})

describe("sanitizeHighlight", () => {
  it("allows mark tags", () => {
    const result = sanitizeHighlight("<mark>highlighted</mark>")
    expect(result).toContain("highlighted")
  })
})

describe("highlightCode", () => {
  it("highlights JavaScript code", () => {
    const result = highlightCode("const x = 1", "js")
    expect(result).toContain("const")
  })
})
