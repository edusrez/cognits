---
name: deepseek-api
description: |
  DeepSeek API integration via OpenAI-compatible streaming chat completions.
  Use when writing or modifying the LLM client, streaming SSE parsing, tool
  call accumulation, DeepSeek reasoning mode, prompt cache optimization,
  model selection cascade, or debugging stream timeouts/silent failures.

  Trigger phrases: DeepSeek API, deepseek, SSE streaming, chat completions,
  thinking mode, reasoning_content, tool calls delta, idle watchdog,
  prompt prefix cache, stream timeout, finish_reason, tool_calls.
target: Internal DeepSeekClient — DeepSeek API (OpenAI-compatible beta)
---
# DeepSeek API Integration

## When to Use

- Writing/modifying `DeepSeekClient` (`internal/llm/deepseek.go`)
- SSE streaming parsing, tool call delta accumulation, reasoning mode config
- Debugging stream timeouts, silent disconnections, or cancellation
- Prompt cache optimization and message ordering
- Model/config cascade (session → global → default)

---

## 1. SSE Wire Parsing

DeepSeek streams Server-Sent Events over HTTP POST. `data:` lines carry JSON chunks;
`data: [DONE]` terminates; non-`data:` lines are ignored.

```go
scanner := bufio.NewScanner(resp.Body)
scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024) // 64KB init, 1MB max

for scanner.Scan() {
    line := scanner.Text()
    if !strings.HasPrefix(line, "data: ") { continue }
    data := strings.TrimPrefix(line, "data: ")
    if data == "[DONE]" { return nil }
    var chunk StreamChunk
    if err := json.Unmarshal([]byte(data), &chunk); err != nil {
        continue // tolerate malformed lines
    }
    onChunk(chunk)
}
```

**Key types:**

```go
type StreamChunk struct {
    Choices []Choice `json:"choices"`
    Usage   *Usage   `json:"usage,omitempty"`
}
type Choice struct {
    Delta        Delta  `json:"delta"`
    FinishReason string `json:"finish_reason"` // "" until final chunk
}
type Delta struct {
    Content          string          `json:"content,omitempty"`
    ReasoningContent string          `json:"reasoning_content,omitempty"`
    ToolCalls        []ToolCallDelta `json:"tool_calls,omitempty"`
}
```

**Rules:**
- `Choices` may be empty → chunk carries only `Usage` (token counts)
- Malformed JSON lines are **skipped**, never abort the stream
- Scanner error after loop: check whether streamCtx or parent ctx was cancelled

---

## 2. Idle Watchdog

Detects silent connection drops (NAT timeout, WiFi dropout) when the server stops sending
without a FIN.

```go
const streamIdleTimeout = 120 * time.Second

streamCtx, cancelStream := context.WithCancel(ctx)
defer cancelStream()

watchdog := time.AfterFunc(streamIdleTimeout, cancelStream)
defer watchdog.Stop()

for scanner.Scan() {
    watchdog.Reset(streamIdleTimeout) // re-arm on every line
    select {
    case <-streamCtx.Done():
        return streamCtx.Err()
    default:
    }
    // ... parse ...
}

if err := scanner.Err(); err != nil {
    // Critical: distinguish watchdog from caller cancellation
    if streamCtx.Err() != nil && ctx.Err() == nil {
        return fmt.Errorf("deepseek: stream inactive for %s: %w", streamIdleTimeout, err)
    }
    return err
}
```

**Error discrimination:** `streamCtx.Err() != nil && ctx.Err() == nil` means the watchdog
fired (derived context cancelled, parent alive). If both cancelled, the caller initiated it.

---

## 3. Reasoning Mode (`thinking.type`)

Binary: `"enabled"` / `"disabled"`. UI values map in:

```go
type deepseekThink struct { Type string `json:"type"` }

var think *deepseekThink
if len(tools) == 0 {
    if reasoning == "disabled" {
        think = &deepseekThink{Type: "disabled"}
    } else {
        think = &deepseekThink{Type: "enabled"} // "high", "max", "" → enabled
    }
}
// With tools: think stays nil → field omitted via omitempty
```

**CRITICAL:** Omit `thinking` entirely when tools are present (`len(tools) > 0`). The API
rejects the combination. The request struct uses `json:"thinking,omitempty"` so `nil`
pointer = field absent.

---

## 4. Per-Phase Timeouts (No Global Timeout)

Streaming responses can run minutes. A global `http.Client.Timeout` kills them mid-stream.
Use transport-level timeouts:

```go
httpClient: &http.Client{
    Transport: &http.Transport{
        DialContext:           (&net.Dialer{Timeout: 10 * time.Second}).DialContext,
        TLSHandshakeTimeout:   10 * time.Second,
        ResponseHeaderTimeout: 60 * time.Second,
        ForceAttemptHTTP2:     true,
    },
    // NEVER set Timeout here
}
```

| Timeout | Duration | Scope |
|---------|----------|-------|
| `DialContext` | 10s | TCP connect |
| `TLSHandshakeTimeout` | 10s | TLS negotiation |
| `ResponseHeaderTimeout` | 60s | Wait for response headers |
| Idle watchdog | 120s | Time between SSE data lines (only runtime timeout during streaming) |

---

## 5. Prompt Cache Preservation

DeepSeek caches the prompt prefix. Identical early tokens skip recomputation.

### Stable tool definitions

Map iteration is random in Go — sort tool names for deterministic prompt order:

```go
func (r *Registry) Definitions() []ToolDefinition {
    names := make([]string, 0, len(r.tools))
    for name := range r.tools { names = append(names, name) }
    sort.Strings(names) // ← keeps prompt identical between requests
    defs := make([]ToolDefinition, 0, len(names))
    for _, name := range names { /* build def */ }
    return defs
}
```

### Message ordering rules

System messages form the cached prefix. Conversation follows:

```
[0] system: Context (User + Location)
[1] system: Formatting rules
[2] system: Agent persona (Maestro)        ← cache prefix ends here
[3] user: [date stamp] message 1
[4] assistant: response 1
[5] user: [date stamp] message 2           ← only this changes per turn
```

To preserve the cache:
- **Front-load** system messages — they're always at the same positions
- **Date stamp only on the LAST user message** — stamping every message changes the prefix
- **Never reorder or modify earlier messages** — append only
- **Storage keeps original content** without date stamps — stamps are LLM-only injection

```go
// Finding the last user message
lastUserIdx := -1
for i, m := range incoming {
    if m.Role == "user" { lastUserIdx = i }
}
// Only prefix the last one
if i == lastUserIdx {
    content = fmt.Sprintf("[%s]\n%s", dateStr, strings.TrimSpace(content))
}
```

### Context injection (also front-loaded)

```go
// 1. User context — fixed position, part of cached prefix
if cfg.UserName != "" || cfg.UserLocation != "" {
    llmMessages = append(llmMessages, llm.Message{Role: "system", Content: ctxParts})
}
// 2. Formatting rules — fixed position
llmMessages = append(llmMessages, llm.Message{Role: "system", Content: formattingRules})
// 3. Agent system prompt — prepended in agent.Run()
```

Cache tracking in usage:
```go
type Usage struct {
    PromptCacheHitTokens  int `json:"prompt_cache_hit_tokens"`
    PromptCacheMissTokens int `json:"prompt_cache_miss_tokens"`
}
```

---

## 6. Tool Call Accumulation from Deltas

Tool calls arrive as **fragments** across multiple chunks, keyed by `index`. Deltas may
arrive out of order or with gaps.

```go
type ToolCallDelta struct {
    Index    int               `json:"index"`
    ID       string            `json:"id,omitempty"`
    Type     string            `json:"type,omitempty"`
    Function FunctionCallDelta `json:"function,omitempty"`
}
type FunctionCallDelta struct {
    Name      string `json:"name,omitempty"`
    Arguments string `json:"arguments,omitempty"` // fragment, not full JSON
}
```

### Accumulator

```go
type toolAccumulator struct {
    ID, Type, Name string
    ArgsBuilder    strings.Builder
}

toolAccs := make(map[int]*toolAccumulator) // keyed by index

for _, tc := range delta.ToolCalls {
    acc := toolAccs[tc.Index]
    if acc == nil { acc = &toolAccumulator{}; toolAccs[tc.Index] = acc }
    if tc.ID != ""   { acc.ID = tc.ID }
    if tc.Type != "" { acc.Type = tc.Type }
    if tc.Function.Name != "" { acc.Name = tc.Function.Name }
    acc.ArgsBuilder.WriteString(tc.Function.Arguments) // always append
}
```

### Sort before processing

When `finishReason == "tool_calls"`, collect indices, sort, then build the tool call list:

```go
// ✅ Correct: collect keys, sort, iterate
indices := make([]int, 0, len(toolAccs))
for idx := range toolAccs { indices = append(indices, idx) }
sort.Ints(indices)

for _, idx := range indices {
    acc := toolAccs[idx]
    toolCalls = append(toolCalls, llm.ToolCall{
        ID: acc.ID, Type: "function",
        Function: llm.ToolCallFunction{Name: acc.Name, Arguments: acc.ArgsBuilder.String()},
    })
}

// ❌ Wrong: assumes contiguous indices 0,1,2 — nil panic when gaps exist
for i := 0; i < len(toolAccs); i++ { acc := toolAccs[i] /* may be nil */ }
```

**Rules:** Only set fields when non-empty. Arguments are fragments — always append, never replace.
Don't assume index order or contiguity.

---

## 7. Finish Reason Handling

```go
if chunk.Choices[0].FinishReason != "" {
    finishReason = chunk.Choices[0].FinishReason
}
```

| Value | Meaning | Action |
|-------|---------|--------|
| `"tool_calls"` | Model wants tools | Accumulate, execute, feed results, iterate |
| `"stop"` | Model finished | Return accumulated content as final |
| `""` (empty) | Streaming in progress | Continue accumulating |

**Usage-only chunks** (empty `Choices`, non-nil `Usage`): handle separately — emit usage,
skip content processing. Usage can also arrive on chunks **with** choices — check `chunk.Usage`
on every chunk.

```go
if len(chunk.Choices) == 0 {
    if chunk.Usage != nil { emit(Event{Type: "usage", Data: chunk.Usage}) }
    return
}
// ... process delta ...
if chunk.Usage != nil { emit(Event{Type: "usage", Data: chunk.Usage}) }
```

---

## 8. Model Selection Cascade

Three-tier resolution: session → global → default.

```go
model := cfg.DeepseekModel          // global
reasoning := cfg.DeepseekReasoning   // global
agentID := cfg.DeepseekAgentId       // global

if sessCfg != nil {
    if sessCfg.Model != ""     { model = sessCfg.Model }
    if sessCfg.Reasoning != "" { reasoning = sessCfg.Reasoning }
    if sessCfg.AgentID != ""   { agentID = sessCfg.AgentID }
}

if model == ""   { model = "deepseek-v4-flash" }
if agentID == "" { agentID = "maestro" }
```

Agent system prompt follows same cascade:
```go
systemPrompt := agent.DefaultAgentPrompt(agentID)
if override := cfg.AgentOverrides[agentID]; override != "" {
    systemPrompt = override
}
```

Subagent config (web_researcher) uses the same pattern with its own defaults:
```go
if webModel == ""     { webModel = "deepseek-v4-flash" }
if webMaxSteps <= 0   { webMaxSteps = 15 }
```

---

## Anti-Patterns

- **NEVER set `http.Client.Timeout`** — kills long-running streams. Use per-phase transport
  timeouts + idle watchdog.
- **NEVER send `thinking` when tools are present** — API rejects the combination.
  Set `think = nil` when `len(tools) > 0`.
- **Don't date-stamp every user message** — only the last one. Stamping all messages breaks
  the prefix cache.
- **Don't iterate tool call indices 0..len-1** — deltas arrive with gaps. Collect keys,
  sort, then iterate.
- **Don't assume the first chunk has `Choices`** — usage-only chunks have empty choices.
- **Don't abort on JSON parse errors** — skip the line and continue.
- **Don't modify earlier messages** — invalidates the prefix cache. Append only.
- **Don't return scanner error without checking context** — watchdog cancellation is
  `context.Canceled`. Use `streamCtx.Err() != nil && ctx.Err() == nil` to identify it.
- **Don't manually build JSON request bodies** — use `json.Marshal` with `omitempty` struct
  tags so optional fields (like `thinking`) are cleanly excluded.

---

## Reference

- [DeepSeek API Docs](https://api-docs.deepseek.com/)
- `internal/llm/llm.go` — types: Message, ToolDef, ToolCall, Delta, StreamChunk, Usage
- `internal/llm/deepseek.go` — streaming client: SSE parsing, watchdog, reasoning, timeouts
- `internal/agent/agent.go` — consumer: tool accumulation, iteration loop with sort
- `internal/server/chat.go` — config cascade, `buildChatMessages`, date stamp logic
- `internal/tools/tools.go` — stable `Definitions()` via `sort.Strings`
- `internal/storage/storage.go` — Config, SubagentConfig types
- `internal/storage/db.go` — SessionConfigRow persistence
