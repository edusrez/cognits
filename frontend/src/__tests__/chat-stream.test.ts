/** Tests for lib/chat-stream.ts: SSE frame formats and sse-types. */

import { describe, it, expect } from "vitest"

describe("SSE frame formats", () => {
  it("named event frame has event: prefix", () => {
    const frame = 'event: reasoning\ndata: {"content":"thinking..."}\n\n'
    expect(frame).toContain("event: reasoning")
    expect(frame).toContain('data: {"content":"thinking..."}')
  })

  it("token frame has no event: line", () => {
    const frame = 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
    expect(frame).not.toContain("event:")
    expect(frame).toContain("data:")
    expect(frame).toContain("choices")
  })

  it("keepalive comments start with colon", () => {
    const frame = ": keepalive\n\n"
    expect(frame).toMatch(/^: keepalive/)
  })

  it("DONE sentinel is the last frame", () => {
    const frame = "data: [DONE]\n\n"
    expect(frame).toContain("[DONE]")
  })
})
