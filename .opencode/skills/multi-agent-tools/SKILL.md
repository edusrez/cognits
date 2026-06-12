---
name: multi-agent-tools
description: |
  Multi-agent architecture patterns for Learn It: tool registries, subagent
  spawning, event relay between orchestrator and subagents, tool call
  accumulation from streaming deltas, and safety limits.

  Use when implementing or modifying the orchestrator agent loop, adding
  new tools, creating subagent types, debugging event relay, or changing
  max steps/cancellation logic.

  Trigger phrases: tool registry, subagent, deploy_subagent, tool accumulator,
  orchestrator loop, event relay, AgentConfig, AgentDef, max steps, ctx.Done,
  agent cancellation, stable-sorted tools, prefix cache, tool call index,
  tool_progress, subagent_end, agent persona, streaming deltas, function call
  accumulation, tool execution loop, multi-agent architecture.
target: Go 1.23+
---
# Multi-Agent Tools Architecture

## When to Use

- Working in `internal/agent/`, `internal/tools/`, `internal/agent/tools/`,
  or `internal/agent/subagents/`
- Adding a new tool to the orchestrator or a subagent
- Creating a new subagent type
- Debugging "tool not found" or "max steps reached" errors
- Modifying how subagent events are relayed to the frontend

---

## 1. Tool Interface

All tools implement a single interface. `Execute` returns `(string, error)` —
a **JSON string**, not a typed object. This keeps the LLM protocol uniform.

```go
// internal/tools/tools.go
type Tool interface {
    Name() string
    Description() string
    Schema() json.RawMessage           // inline JSON Schema for parameters
    Execute(ctx context.Context, args json.RawMessage) (string, error)
}
```

- **`Schema()`** returns `json.RawMessage` — raw inline JSON, not marshalled
  from a struct, to avoid double-encoding
- **`Execute()`** returns a JSON string. On domain errors, return
  `{"error": "msg"}` as the string — never return a Go `error` for recoverable
  failures; the LLM reads the JSON output as a tool result

**Implementation pattern:**

```go
func (t *searchTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
    var a struct { Query string `json:"query"` }
    if err := json.Unmarshal(args, &a); err != nil {
        return toolError("invalid args: " + err.Error()), nil
    }
    resp, err := t.client.Search(ctx, a.Query)
    if err != nil {
        return toolError(err.Error()), nil
    }
    data, _ := json.Marshal(resp)
    return string(data), nil
}
func toolError(msg string) string {
    data, _ := json.Marshal(map[string]string{"error": msg})
    return string(data)
}
```

---

## 2. Stable-Sorted Tool Definitions (Prefix Cache)

Go maps iterate in random order. If tool definitions are built from a
`map[string]Tool`, the JSON array order changes between requests. DeepSeek
uses a **prefix cache** — byte-identical system prompt + tools = cache hit.
Random order = cache miss every request.

**Solution:** `Definitions()` sorts tool names with `sort.Strings`:

```go
func (r *Registry) Definitions() []ToolDefinition {
    names := make([]string, 0, len(r.tools))
    for name := range r.tools {
        names = append(names, name)
    }
    sort.Strings(names) // ← deterministic order = cache hits

    defs := make([]ToolDefinition, 0, len(names))
    for _, name := range names {
        t := r.tools[name]
        defs = append(defs, ToolDefinition{
            Type: "function",
            Function: ToolFunction{
                Name: t.Name(), Description: t.Description(), Parameters: t.Schema(),
            },
        })
    }
    return defs
}
```

One registry per agent instance. The orchestrator's registry contains only
`deploy_subagent`. The web_researcher subagent has a separate registry with
`tinyfish_search` + `tinyfish_fetch_content`.

---

## 3. Orchestrator Iteration Loop

```go
// internal/agent/agent.go
func (a *Agent) Run(ctx context.Context, messages []llm.Message, emit func(Event)) (string, error) {
    if a.SystemPrompt != "" {
        messages = append([]llm.Message{{Role: llm.RoleSystem, Content: a.SystemPrompt}}, messages...)
    }
    toolDefs := a.Tools.Definitions() // sorted

    for iteration := 0; a.MaxSteps == 0 || iteration < a.MaxSteps; iteration++ {
        select {
        case <-ctx.Done():
            return "", fmt.Errorf("agent: cancelled after %d steps: %w", iteration, ctx.Err())
        default:
        }

        // Stream LLM → accumulate content + tool calls simultaneously
        content, toolAccs, finishReason := streamAndAccumulate(ctx, messages, toolDefs, emit)

        // No tool calls → return text to caller
        if len(toolAccs) == 0 || finishReason != "tool_calls" {
            return content, nil
        }

        // Build assistant message with tool calls, sort indices, execute tools
        messages = append(messages, buildAssistantMsg(content, toolAccs))
        for _, tc := range sortedToolCalls(toolAccs) {
            emitToolStart(tc)
            result := executeTool(tc)
            emitToolEnd(tc)
            messages = append(messages, llm.Message{Role: llm.RoleTool, Content: result, ToolCallID: tc.ID})
        }
    }
    return "", fmt.Errorf("agent: max steps reached (%d)", a.MaxSteps)
}
```

Loop structure: stream → accumulate → sort tool calls → execute sequentially →
feed results as `role: tool` → repeat. System prompt prepended once at start.

---

## 4. Tool Call Accumulator Pattern

Tool calls arrive in streaming deltas, not a single chunk. Each delta carries:
`index`, `id`, `type`, `function.name`, `function.arguments`. Arguments are
streamed as partial JSON fragments — concatenate with `strings.Builder`.

```go
type toolAccumulator struct {
    ID          string
    Type        string
    Name        string
    ArgsBuilder strings.Builder
}

// In stream callback:
var toolAccs map[int]*toolAccumulator
for _, tc := range delta.ToolCalls {
    acc := toolAccs[tc.Index]
    if acc == nil {
        acc = &toolAccumulator{}
        toolAccs[tc.Index] = acc
    }
    if tc.ID != ""          { acc.ID = tc.ID }
    if tc.Type != ""        { acc.Type = tc.Type }
    if tc.Function.Name != "" { acc.Name = tc.Function.Name }
    acc.ArgsBuilder.WriteString(tc.Function.Arguments)
}
```

**After streaming ends, sort indices before building the ToolCall array:**

```go
// CRITICAL: use sorted map keys — deltas may arrive out of order
indices := make([]int, 0, len(toolAccs))
for idx := range toolAccs {
    indices = append(indices, idx)
}
sort.Ints(indices)

toolCalls := make([]llm.ToolCall, 0, len(toolAccs))
for _, idx := range indices {
    acc := toolAccs[idx]
    toolCalls = append(toolCalls, llm.ToolCall{
        ID: acc.ID, Type: "function",
        Function: llm.ToolCallFunction{
            Name: acc.Name, Arguments: acc.ArgsBuilder.String(),
        },
    })
}
```

The assistant message (with `ToolCalls`) is appended to messages **before**
executing the tools — `role: tool` responses must follow the assistant
message that requested them per the OpenAI protocol.

---

## 5. Tool Execution

After building the assistant message, each tool executes sequentially:

```go
for _, tc := range toolCalls {
    tool, ok := a.Tools.Get(tc.Function.Name)
    if !ok {
        return "", fmt.Errorf("agent: unknown tool: %s", tc.Function.Name)
    }
    emit(Event{Type: "tool_start", Data: map[string]interface{}{
        "tool": tc.Function.Name, "args": tc.Function.Arguments, "id": tc.ID,
    }})
    result, err := tool.Execute(ctx, json.RawMessage(tc.Function.Arguments))
    if err != nil {
        errJSON, _ := json.Marshal(map[string]string{"error": err.Error()})
        result = string(errJSON)
    }
    emit(Event{Type: "tool_end", Data: map[string]interface{}{
        "tool": tc.Function.Name, "id": tc.ID,
    }})
    messages = append(messages, llm.Message{
        Role: llm.RoleTool, Content: result, ToolCallID: tc.ID,
    })
}
```

If `err != nil` (infrastructure failure), the error is JSON-wrapped and fed
back as the tool result — the LLM sees `{"error": "..."}`. `tool_start` and
`tool_end` events drive the frontend progress indicator.

---

## 6. Subagent Spawning (deploy_subagent)

The orchestrator's only tool. It creates a new `Agent` instance with its own
config, runs it synchronously, and persists the result as a report.

```go
// internal/agent/tools/deploy.go
func (t *DeploySubagent) Execute(ctx context.Context, args json.RawMessage) (string, error) {
    var parsed deploySubagentArgs  // {Type, Query}
    json.Unmarshal(args, &parsed)

    cfg := t.Subagents[parsed.Type] // lookup config by type (e.g. "web_researcher")
    reportID := storage.NewReportID() // "r_" + 16 random hex chars

    orchestrator := agent.New(*cfg, t.LLMClient)
    content, err := orchestrator.Run(ctx, []llm.Message{
        {Role: llm.RoleUser, Content: parsed.Query},
    }, relayEvent)

    // Extract title (first # heading), summary (first para, max 200 chars)
    report := storage.Report{
        ID: reportID, SessionID: sessionID,
        Title: extractTitle(content, parsed.Query),
        Content: content, Summary: extractSummary(content),
    }
    t.ReportStore.Save(report)

    t.Emit(agent.Event{Type: "subagent_end", Data: map[string]interface{}{
        "reportId": reportID, "title": title, "summary": report.Summary,
    }})

    result, _ := json.Marshal(map[string]interface{}{"reportId": reportID, ...})
    return string(result), nil
}
```

**Key design decisions:**
- **Synchronous** — subagent runs to completion in one tool call
- **Own Agent instance** with own system prompt, tool registry (TinyFish),
  max steps (15), and model/reasoning config
- **Inherits parent context** — cancellation propagates automatically
- **`subagent_end` is emitted by the tool**, not the subagent — ensures the
  report is fully persisted before the frontend tries to load it

---

## 7. Event Relay Between Agents

The `deploy_subagent` tool injects a custom `emit` function that **filters
and translates** subagent events:

```go
emit := func(ev agent.Event) {
    switch ev.Type {
    case "reasoning":
        // SUPPRESSED → replaced with generic progress
        t.Emit(agent.Event{Type: "tool_progress",
            Data: map[string]interface{}{"message": "Pensando..."}})
        return
    case "token":
        return // SUPPRESSED — internal chain-of-thought is noise
    case "tool_start":
        tool, _ := ev.Data.(map[string]interface{})["tool"].(string)
        msg := "Buscando en la Web"
        if tool == "tinyfish_fetch_content" { msg = "Leyendo Resultados" }
        t.Emit(agent.Event{Type: "tool_progress",
            Data: map[string]interface{}{"message": msg}})
    default:
        t.Emit(ev) // Forward as-is (usage, errors)
    }
}
```

| Subagent Event | Relay Behavior | Frontend Sees |
|---|---|---|
| `token` | SUPPRESSED | Nothing (report at end) |
| `reasoning` | SUPPRESSED → replaced | `tool_progress: "Pensando..."` |
| `tool_start` (search) | TRANSLATED | `tool_progress: "Buscando en la Web"` |
| `tool_start` (fetch) | TRANSLATED | `tool_progress: "Leyendo Resultados"` |
| `usage`, `error` | FORWARDED | As-is |
| `subagent_end` | EMITTED by deploy tool | Report ID + title + summary |

In chat.go, the server's `processEvent` accumulates `tool_progress` →
`sa.ToolStatus` (UI status indicator) and `subagent_end` →
`sa.LiveReportID`/`sa.LiveReportTitle` (clickable report link).

---

## 8. Agent Persona System

```go
type AgentDef struct {
    ID           string `json:"id"`
    Name         string `json:"name"`
    SystemPrompt string `json:"systemPrompt"`
}

var DefaultAgents = []AgentDef{
    {ID: "maestro", Name: "Maestro", SystemPrompt: maestroSystemPrompt},
}
func DefaultAgentPrompt(id string) string {
    for _, a := range DefaultAgents {
        if a.ID == id { return a.SystemPrompt }
    }
    return maestroSystemPrompt
}
```

Resolved via the three-tier config cascade: session `agentId` → global config
→ `"maestro"`. Users can override system prompts per persona via
`AgentOverrides` in global config.

---

## 9. Safety Limits: Max Steps + Cancellation

```go
// chat.go
const (
    orchestratorMaxSteps      = 25
    defaultResearcherMaxSteps = 15
)
```

- **Orchestrator (25)**: one step = one LLM call + tool exec. With only
  `deploy_subagent`, that's up to 25 research cycles.
- **Researcher (15)**: one step = search or fetch + analysis. Sufficient for
  multi-turn research with the methodology's stop criteria.

**Cancellation via context:**

```go
// At the top of each iteration:
select {
case <-ctx.Done():
    return "", fmt.Errorf("agent: cancelled after %d steps: %w", iteration, ctx.Err())
default:
}
```

`chat.go` creates the parent context with `context.WithCancel`. User clicks
"stop" → `handleCancelAgent` calls `sa.Cancel()` → both orchestrator and
subagent stop at their next iteration check. Partial content is saved in
the `defer` cleanup.

---

## 10. Wiring: chat.go

```go
// Resolve config cascade → model, reasoning, agentId
subagentMap := map[string]*agent.AgentConfig{
    "web_researcher": researcherCfg, // from subagents.ResearcherConfig()
}
registry := tools.NewRegistry()
registry.Register(&agenttools.DeploySubagent{
    LLMClient: llmClient, ReportStore: s.reportStore,
    Subagents: subagentMap, SessionID: func() string { return sid },
    Emit: processEvent,
})
ag := agent.New(agent.AgentConfig{
    Name: "orchestrator", Model: model, Reasoning: reasoning,
    MaxSteps: orchestratorMaxSteps, SystemPrompt: systemPrompt,
    Tools: registry, Subagents: subagentMap,
}, llmClient)

go func() {
    persistMessages(sid, storageMessages)
    defer cleanup()
    ag.Run(ctx, llmMessages, processEvent)
}()
```

`Subagents` map is passed to **both** `AgentConfig` and `DeploySubagent` —
the tool uses it as a config registry keyed by subagent type name.

---

## Event Flow Diagram

```
Orchestrator Agent                 DeploySubagent Tool            Web Researcher Subagent
─────────────────                 ────────────────────            ────────────────────────
LLM stream                          agent.New(cfg, llm)            LLM stream
  ├─ token ──────────► UI            ├─ Run(ctx, msgs, relay)       ├─ token ──┐
  ├─ reasoning ──────► UI            │                                 reasoning │  SUPPRESSED
  ├─ tool_start ─────► UI            │                              ├─ tool_start ─► "Buscando..." / "Leyendo..."
  │  tool_end ───────► UI            │                              ├─ usage ─── FORWARDED
  │  finish_reason=                  │                              │
  │  "tool_calls"                    │◄── subagent finishes ────────┤
  │                                  │                              │
  │                          extractTitle() + extractSummary()      │
  │                          reportStore.Save()                     │
  │                          emit("subagent_end") ──────► UI        │
  │                          return JSON result                     │
  ├─ role:tool ◄── feeds result back to LLM                        │
  │                                                                 │
  finish_reason="stop" ──────────► final content to UI              │
```

---

## Anti-Patterns

### Don't let subagents communicate directly with each other
Only the orchestrator spawns subagents. Subagents never call each other.
The orchestrator receives the report and decides whether to spawn another.

### Don't expose subagent's internal reasoning to the user
Subagent `token` and `reasoning` events are suppressed in the relay. The
user only sees `tool_progress` messages and the final report.

### Don't iterate tool call indices assuming 0..len-1
Deltas arrive out of order. Use sorted map keys:
```go
// WRONG: for i := 0; i < len(toolAccs); i++ { ... } — panics on sparse maps
// RIGHT:
indices := make([]int, 0, len(toolAccs))
for idx := range toolAccs { indices = append(indices, idx) }
sort.Ints(indices)
for _, idx := range indices { acc := toolAccs[idx] }
```

### Don't create tool definitions in random map order
```go
// WRONG: for _, tool := range registry.tools { ... } — kills prefix cache
// RIGHT: sort names first, then iterate
```

### Don't use INSERT OR REPLACE on FTS5 external content tables
`REPLACE` does `DELETE` + `INSERT` but doesn't fire delete triggers (without
`recursive_triggers` pragma). Use `INSERT ... ON CONFLICT DO UPDATE` instead.

### Don't put tool results in the system prompt
Results go in `role: tool` messages, paired via `tool_call_id`. Putting them
elsewhere breaks the multi-turn tool-calling protocol.

### Don't set MaxSteps to 0 without a context deadline
`MaxSteps == 0` disables the step limit. Without a deadline, a buggy tool
or loop runs forever. Always set at least one safety limit.

---

## Reference

- `internal/agent/agent.go` — Orchestrator loop, tool accumulation, stream handling
- `internal/tools/tools.go` — Tool interface, Registry, stable-sorted Definitions
- `internal/agent/tools/deploy.go` — DeploySubagent, event relay, report persistence
- `internal/agent/subagents/researcher.go` — Web researcher config, TinyFish tools, system prompt
- `internal/agent/prompts.go` — Agent personas (AgentDef, DefaultAgents)
- `internal/server/chat.go` — Orchestrator wiring, config cascade, cancellation
- `internal/storage/db.go` — ReportStore, FTS5 schema, NewReportID
- `internal/llm/llm.go` — LLM protocol types (Message, ToolCall, Delta, StreamChunk)
- [DeepSeek Context Caching](https://api-docs.deepseek.com/guides/context_caching)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
