---
name: sse-streaming
description: |
  Server-Sent Events streaming patterns for the Learn It project — both Go
  server-side (session_stream.go, chat.go, server.go) and SolidJS frontend-side
  (chat-stream.ts, chat-store.ts). Covers history snapshots, mutex + channel
  fan-out, keepalive, draining, timeouts, graceful shutdown, inactive-agent
  fallback, ReadableStream SSE parsing, token batching, and AbortController
  lifecycle.
  Trigger phrases: SSE, Server-Sent Events, event stream, text/event-stream,
  streaming endpoint, keepalive, fan-out, history snapshot, ReadableStream SSE,
  EventSource alternative, token batching, AbortController SSE, SessionAgent,
  chan agent.Event, non-blocking send.
target: Go 1.23+ · SolidJS 1.9+ · Tailwind CSS 4
---

# SSE Streaming Patterns (Go + SolidJS)

## When to Use

- Writing SSE endpoints (`text/event-stream`) or subscribing to live agent events
- Debugging dropped events, race conditions, dead connections, or token duplication
- Adding event types to the stream or replacing `EventSource` with `fetch()` + `ReadableStream`
- Understanding why `ReadTimeout`/`WriteTimeout` break SSE

---

## 1. SSE Wire Format

Three event structures, all using `\n\n` as the frame delimiter.

```go
// Typed event: event line + data line
fmt.Fprintf(w, "event: history\ndata: %s\n\n", jsonData)

// Inline delta (token stream): data line only, no event line
fmt.Fprintf(w, "data: %s\n\n", jsonData)

// Keepalive comment: colon-space prefix, no data line
fmt.Fprintf(w, ": keepalive\n\n")
```

**SSE headers** — always set these exactly:

```go
w.Header().Set("Content-Type", "text/event-stream")
w.Header().Set("Cache-Control", "no-cache")
w.Header().Set("Connection", "keep-alive")
w.Header().Set("X-Accel-Buffering", "no") // nginx: don't buffer the stream
```

**Why each header matters:**

| Header | Without it |
|---|---|
| `Cache-Control: no-cache` | Browsers/proxies may cache event data |
| `Connection: keep-alive` | HTTP/1.1 proxies may close after first flush |
| `X-Accel-Buffering: no` | nginx buffers output; client sees nothing until stream ends |

**Flusher requirement:** Assert `http.Flusher` at the start. After every write, call `Flush()` so bytes reach the client immediately.

```go
flusher, ok := w.(http.Flusher)
if !ok { http.Error(w, "streaming unsupported", http.StatusInternalServerError); return }
// Every write: fmt.Fprintf(w, ...); flusher.Flush()
```

---

## 2. History Snapshot on Connect (Race-Free Initial State)

New SSE subscribers must receive the **full message list + live agent state** BEFORE any live events. Otherwise, tokens may arrive before the client knows what messages already exist, causing display corruption.

```go
// Lock → snapshot → send → unlock → forward live events
sa.mu.RLock()
msgSnapshot := make([]map[string]interface{}, 0, len(sa.Messages))
for _, m := range sa.Messages {
    msgSnapshot = append(msgSnapshot, map[string]interface{}{
        "role": m.Role, "content": m.Content, "reasoning": m.Reasoning,
        "reportId": m.ReportID, "reportTitle": m.ReportTitle,
    })
}
historyData, _ := json.Marshal(map[string]interface{}{
    "messages": msgSnapshot, "toolStatus": sa.ToolStatus,
    "liveContent": sa.LiveContent, "liveReasoning": sa.LiveReasoning,
    "liveReportId": sa.LiveReportID, "liveReportTitle": sa.LiveReportTitle,
    "agentActive": true,
})
sa.mu.RUnlock()
fmt.Fprintf(w, "event: history\ndata: %s\n\n", string(historyData))
flusher.Flush()
```

✅ Lock before snapshot, unlock after flush — no events can interleave between snapshot and live forwarding.
❌ Don't send history after forwarding live events — client gets partial state.

---

## 3. Event Fan-Out with Mutex + Channels

`SessionAgent` holds subscribers in a `map[chan agent.Event]struct{}` protected by `sync.RWMutex`. `Emit()` fans events out via **non-blocking sends** — the agent goroutine must never block on a slow client.

```go
type SessionAgent struct {
    SessionID string
    Cancel    context.CancelFunc
    Done      chan struct{}            // closed when agent goroutine exits

    mu              sync.RWMutex
    Messages        []storage.MessageRow // source of truth for history snapshots
    LiveContent     string             // accumulated streaming text
    LiveReasoning   string             // accumulated reasoning
    ToolStatus      string             // current tool status (or "")
    LiveReportID    string             // set when subagent finishes
    LiveReportTitle string
    Subscribers     map[chan agent.Event]struct{}
}
```

**Subscribe / Unsubscribe / Emit:**

```go
func (sa *SessionAgent) Subscribe() chan agent.Event {
    ch := make(chan agent.Event, 1024) // buffered: drops unlikely
    sa.mu.Lock(); sa.Subscribers[ch] = struct{}{}; sa.mu.Unlock()
    return ch
}
func (sa *SessionAgent) Unsubscribe(ch chan agent.Event) {
    sa.mu.Lock(); delete(sa.Subscribers, ch); sa.mu.Unlock()
}
// Non-blocking send: agent never blocks. DB reload on "done" = safety net.
func (sa *SessionAgent) Emit(event agent.Event) {
    sa.mu.RLock(); defer sa.mu.RUnlock()
    for ch := range sa.Subscribers {
        select { case ch <- event: default: }
    }
}
```

✅ Non-blocking send (`select` with `default`) — agent never hangs.
✅ `RLock` (read lock) on `Emit` — multiple subscribers can be notified concurrently.
✅ DB reload on `done` recovers any dropped events.
❌ Don't use blocking sends (`ch <- event` without `default`) — one slow client blocks the agent.
❌ Don't use `Lock` (write lock) on `Emit` — prevents concurrent fan-out.

---

## 4. Keepalive (Dead Connection Detection)

SSE connections can be silently dropped by proxies or browsers. A 15s ticker writes a comment line (`": keepalive\n\n"`) — if the write fails, the goroutine exits.

```go
ticker := time.NewTicker(15 * time.Second)
defer ticker.Stop()

for {
    select {
    case ev := <-ch:
        forward(ev)
    case <-sa.Done:
        drainPending(ch, forward)
        writeEvent("done", nil)
        return
    case <-r.Context().Done():
        return                          // client disconnected
    case <-ticker.C:
        fmt.Fprintf(w, ": keepalive\n\n") // comment line — no client-side event
        flusher.Flush()
    }
}
```

✅ 15-second interval — fast enough to detect dead connections, slow enough to avoid overhead.
✅ Comment format (`": keepalive\n\n"`) — ignored by SSE parsers, no client-side event fires.
❌ Don't skip keepalive — silent connection drops go undetected, goroutines leak.
❌ Don't send data keepalives (e.g., `data: ping\n\n`) — clients process them as real events.

---

## 5. Draining Before `done`

When the agent finishes (`Done` channel closes), drain all remaining events from the subscriber channel before sending `event: done`. This prevents lost events queued between the agent's final event and `close(sa.Done)`.

```go
case <-sa.Done:
    // Drain pending events before closing the stream.
    for {
        select {
        case ev := <-ch:
            forward(ev)
        default:
            writeEvent("done", nil)
            return
        }
    }
```

The `default` branch fires when the channel is empty — at that point, all events have been forwarded and it's safe to send `done`.

✅ Drain loop with `select` + `default` — ensures channel is truly empty.
❌ Don't send `done` without draining — last few events may never reach the client.
❌ Don't send `done` before the `Done` channel closes — clients disconnect early.

---

## 6. Server Timeouts (Critical for SSE)

**Never set `ReadTimeout` or `WriteTimeout` on the `http.Server`.** These are global timeouts that apply to all connections — including long-lived SSE streams. SSE connections can last minutes or hours; any write timeout would kill them.

```go
srv := &http.Server{
    Handler:           s.Mux,
    ReadHeaderTimeout: 10 * time.Second,  // ✅ safe: only header-reading phase
    IdleTimeout:       120 * time.Second,  // ✅ safe: idle connections (between keepalives)
    // ReadTimeout:   NEVER set this — kills SSE
    // WriteTimeout:  NEVER set this — kills SSE
}
```

✅ `ReadHeaderTimeout` — bounds the header-reading phase without affecting streaming.
✅ `IdleTimeout` — cleans up connections with no activity at all.
✅ Keepalive (15s) beats `IdleTimeout` (120s) — writes reset the idle timer.
❌ Never `ReadTimeout` — kills all connections mid-stream.
❌ Never `WriteTimeout` — kills SSE on the first write after the timeout window.

---

## 7. Graceful Shutdown (Client Disconnect)

When a client disconnects, `r.Context().Done()` fires. The SSE goroutine exits cleanly — `defer Unsubscribe()` handles channel cleanup.

```go
ch := sa.Subscribe()
s.agentMu.Unlock()
defer sa.Unsubscribe(ch)   // ✅ always called
// ... headers, history, then select loop from §4 ...
```

✅ `defer Unsubscribe` — channel removed from map regardless of exit path.
❌ Don't forget to unsubscribe — channel stays in map forever, goroutine leak.

---

## 8. Inactive Agent Fallback

If no agent is running (already finished or never started), load messages from SQLite and send as `event: history` + `event: done`. No keepalive needed — the stream is short-lived.

```go
func (s *Server) sendMessagesSnapshot(w http.ResponseWriter, r *http.Request, sid string) {
    rows, err := s.reportStore.LoadMessages(sid)
    if err != nil { http.Error(w, err.Error(), http.StatusInternalServerError); return }

    messages := make([]map[string]interface{}, 0, len(rows))
    for _, row := range rows {
        messages = append(messages, map[string]interface{}{
            "role": row.Role, "content": row.Content, "reasoning": row.Reasoning,
        })
    }
    historyData, _ := json.Marshal(map[string]interface{}{"messages": messages})

    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    fmt.Fprintf(w, "event: history\ndata: %s\n\n", string(historyData))
    fmt.Fprintf(w, "event: done\ndata: {}\n\n")
    // No flusher/keepalive — data is small and handler returns immediately.
}
```

The check in the main handler:

```go
s.agentMu.Lock()
sa, exists := s.activeAgents[sid]
if !exists {
    s.agentMu.Unlock()
    s.sendMessagesSnapshot(w, r, sid) // agent not running → DB fallback
    return
}
ch := sa.Subscribe()
s.agentMu.Unlock()
defer sa.Unsubscribe(ch)
// ... live streaming loop ...
```

✅ Same `event: history` format for both paths — clients don't care about source.
✅ Immediately send `event: done` after history — client knows the stream is complete.
✅ No flusher/keepalive needed for the inactive path.

---

## 9. SSE Fetch Wrapper (Not EventSource)

The browser-native `EventSource` API lacks custom headers, `POST`, and `AbortController` support. Use `fetch()` with `ReadableStream` instead.

```typescript
export async function streamSession(
  sessionId: string, callbacks: StreamCallbacks, abortSignal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/sessions/${sessionId}/stream`, { signal: abortSignal })
  if (!response.ok) { callbacks.onError(new Error(`HTTP ${response.status}`)); return }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = "", currentEvent = "message"  // default: inline delta

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Split on SSE frame delimiter (\n\n), keep incomplete last chunk
    const events = buffer.split("\n\n")
    buffer = events.pop() || ""

    for (const event of events) {
      const lines = event.split("\n")
      for (const line of lines) {
        if (line.startsWith("event: ")) { currentEvent = line.slice(7); continue }
        if (!line.startsWith("data: ")) continue
        try {
          const json = JSON.parse(line.slice(6))
          // Typed events: use currentEvent set by "event:" line
          if (currentEvent === "history")       callbacks.onHistory(json)
          else if (currentEvent === "done")     { callbacks.onDone(); return }
          else if (currentEvent === "reasoning") callbacks.onReasoning(json.content || "")
          else if (currentEvent === "error")     callbacks.onServerError?.(json.message || "")
          else if (currentEvent === "tool_start")  callbacks.onToolStart?.(json)
          else if (currentEvent === "tool_progress") callbacks.onToolProgress?.(json)
          else if (currentEvent === "tool_end")   callbacks.onToolEnd?.(json)
          else if (currentEvent === "subagent_end") callbacks.onSubagentEnd?.(json)
          else if (currentEvent === "usage")    callbacks.onUsage(json)
          else {
            // Default "message": parse inline delta
            const c = json.choices?.[0]?.delta?.content
            const r = json.choices?.[0]?.delta?.reasoning_content
            if (r) callbacks.onReasoning(r)
            if (c) callbacks.onToken(c)
            if (json.usage) callbacks.onUsage(json.usage)
          }
        } catch { /* skip unparseable chunks */ }
      }
      currentEvent = "message"  // reset for next event
    }
  }
  callbacks.onDone()
}
```

✅ `fetch()` + `ReadableStream` — custom headers, `AbortController`, full control. Frame-aware parsing handles partial TCP frames. `currentEvent` tracking enables typed + inline delta coexistence.
❌ Don't use `EventSource` — no headers, no abort, no POST.

---

## 10. Token Batching (50ms Flush)

SSE delivers one token per event. Updating the store per-token triggers dozens of re-renders/sec — UI becomes janky. Accumulate in a buffer and flush every 50ms.

```typescript
const pendingTokens = new Map<string, { content: string; reasoning: string }>()
let flushTimer: ReturnType<typeof setTimeout> | null = null

function scheduleFlush() {
  if (flushTimer !== null) return
  flushTimer = setTimeout(flushPendingTokens, 50)   // 50ms batch window
}

function flushPendingTokens() {
  if (flushTimer !== null) { clearTimeout(flushTimer); flushTimer = null }
  if (pendingTokens.size === 0) return
  batch(() => {
    setMessagesBySession((prev) => {
      const next = { ...prev }
      for (const [sid, buf] of pendingTokens) {
        const ses = next[sid] ?? []
        const last = ses[ses.length - 1]
        if (last?.role !== "assistant") continue
        next[sid] = [...ses.slice(0, -1), {
          ...last, content: last.content + buf.content,
          ...(buf.reasoning ? { reasoning: (last.reasoning ?? "") + buf.reasoning } : {}),
        }]
      }
      return next
    })
  })
  pendingTokens.clear()
}
```

Callbacks push to buffer and schedule flush:

```typescript
onToken(tok: string) {
  let buf = pendingTokens.get(sid) ?? { content: "", reasoning: "" }
  buf.content += tok; pendingTokens.set(sid, buf); scheduleFlush()
}
```

✅ `batch()` wraps store update — one re-render per flush. `setTimeout` (not `rAF`) avoids background-tab freezes.
❌ Don't update per-token (jank). Don't use `rAF` (background tabs never flush). Don't forget to flush on `onDone`/`onSubagentEnd`.

---

## 11. AbortController Lifecycle

One active SSE stream at a time across the app. On session switch or unmount, abort the previous stream immediately.

```typescript
let streamController: AbortController | null = null

export function subscribeToSession(sid: string) {
  streamController?.abort()              // kill previous stream
  const controller = new AbortController()
  streamController = controller

  streamSession(
    sid,
    createStreamCallbacks(sid, controller),
    controller.signal,                   // passed to fetch()
  ).catch(() => {
    if (streamController === controller) {
      streamController = null
      setStreamState(sid, { active: false, thinking: false })
    }
  })
}
```

In SolidJS, the `onCleanup` lifecycle hook cleans up on component unmount:

```typescript
onCleanup(() => {
  streamController?.abort()
  streamController = null
})
```

✅ One active stream at a time — abort old before creating new.
✅ `.catch()` guards — if aborted, skip state updates from the old controller.
✅ `AbortController.signal` passed to `fetch()` — browser cancels the TCP connection immediately.
❌ Don't create multiple concurrent streams for the same session — duplicate tokens.
❌ Don't forget cleanup on unmount — SSE stream lives forever, goroutine leak server-side.

---

## 12. Event Type Handling (Typed vs. Inline Delta)

The SSE stream mixes two formats — typed events (`event: <type>\n`) for structure, and inline deltas (no event line) for streaming tokens. The parser tracks `currentEvent` and resets to `"message"` after each event.

```typescript
let currentEvent = "message"
for (const line of lines) {
  if (line.startsWith("event: ")) { currentEvent = line.slice(7); continue }
  if (!line.startsWith("data: ")) continue
  // currentEvent was set by preceding "event:" line (if any)
  if (currentEvent === "history")             { /* ... */ }
  else if (currentEvent === "done")           { /* ... */ }
  else if (currentEvent === "reasoning")      { /* ... */ }
  else {
    // "message" (default) — inline delta for streaming tokens
    const content = json.choices?.[0]?.delta?.content
    if (content) callbacks.onToken(content)
  }
}
currentEvent = "message"  // reset after each event
```

✅ Two-format coexistence — typed events for structure, inline deltas for streaming. Reset `currentEvent` after each event to prevent bleed.
❌ Don't use only inline deltas — clients need typed events for state transitions.

---

## Anti-Patterns

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| `ReadTimeout` / `WriteTimeout` on `http.Server` | Kills all long-lived SSE connections mid-stream | Use only `ReadHeaderTimeout` + `IdleTimeout` |
| Using `EventSource` browser API | No custom headers, no `AbortController`, no `POST` | Use `fetch()` + `ReadableStream` |
| Sending `event: done` before draining pending events | Last events in channel are lost | Drain with `select { case ev := <-ch: forward(ev); default: done }` |
| No keepalive (or keepalive too slow) | Dead connections never detected; goroutines leak | 15-second ticker with `": keepalive\n\n"` comment |
| Blocking send on subscriber channel (`ch <- event`) | One slow client blocks the agent goroutine | Non-blocking `select { case ch <- event: default: }` with buffer |
| Updates to store per-token (no batching) | 30-50 re-renders/sec, janky UI | 50ms buffer + `batch()` flush |
| `requestAnimationFrame` for flush scheduling | `rAF` pauses in background tabs, tokens pile up | `setTimeout(fn, 50)` |
| Multiple concurrent SSE streams for same session | Duplicate tokens, conflicting state | One `AbortController`, abort old before creating new |
| Forgetting `onCleanup` in SolidJS | SSE stream lives forever after component unmount | `onCleanup(() => streamController?.abort())` |
| `Lock` (write lock) instead of `RLock` on `Emit` | Prevents concurrent fan-out to subscribers | `RLock` — multiple subscribers can read concurrently |

---

## Reference

- [MDN: Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [MDN: ReadableStream](https://developer.mozilla.org/en-US/docs/Web/API/ReadableStream)
- [SolidJS: batch()](https://docs.solidjs.com/reference/reactive-utilities/batch)
- [SolidJS: onCleanup()](https://docs.solidjs.com/reference/lifecycles/oncleanup)
- [Go: http.Flusher](https://pkg.go.dev/net/http#Flusher)
- [Go: http.Server timeouts](https://pkg.go.dev/net/http#Server)
- Source files: `internal/server/session_stream.go`, `internal/server/chat.go`, `internal/server/server.go`, `frontend/src/lib/chat-stream.ts`, `frontend/src/stores/chat-store.ts`
