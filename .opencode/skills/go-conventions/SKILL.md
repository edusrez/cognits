---
name: go-conventions
description: |
  Go idioms, best practices, and conventions for backend development.
  Use when writing Go code, structuring packages, handling errors,
  writing HTTP servers, using embed, or working with SQLite.
  Trigger phrases: Go package layout, cmd/internal pattern, error wrapping,
  %w, sentinel error, errors.Is, errors.As, table-driven test, t.Run,
  go:embed, embed.FS, fs.Sub, database/sql, sql.Open, sqlite3 driver,
  ncruces/go-sqlite3, CGO_ENABLED, strings.Builder, net/http ServeMux,
  Go constructor, Go interface design, Go naming conventions.
target: Go 1.23+
---

# Go Backend Conventions (1.23+)

## When to Use

- Writing Go packages in `cmd/` or `internal/`
- HTTP handlers with `net/http` (Go 1.22+ method routing)
- Interfaces, constructors, dependency injection
- Error wrapping with `fmt.Errorf` + `%w`
- Embedding static assets with `go:embed`
- SQLite with `database/sql`, no CGo (`ncruces/go-sqlite3`)
- Writing/reviewing Go tests

---

## 1. Project Structure

Prefer `cmd/` + `internal/`. Flat is better than deep. Group by feature.

```
cmd/learnit/main.go
internal/
  server/    # HTTP server, routes
  agent/     # Business logic
  llm/       # External API client
  storage/   # Persistence
  tools/     # Interface + impls
```

- `cmd/` — one package per binary; only `package main`
- `internal/` — importable only within this module
- Avoid `pkg/` unless the library is intentionally public

---

## 2. Error Handling

Always wrap with `%w` to preserve the error chain. Prefix with `package:operation`.

```go
return fmt.Errorf("server: loading config: %w", err) // %w preserves the chain
```

Sentinel errors and type extraction:

```go
var ErrNotInitialized = fmt.Errorf("storage: .learnit/ not initialized")
if errors.Is(err, storage.ErrNotInitialized) { ... }
var netErr *net.OpError
if errors.As(err, &netErr) { ... }
```

---

## 3. Constructors

Return pointers. Accept dependencies explicitly. Name `New` or `New<T>`.

```go
func New() *Server { return &Server{Mux: http.NewServeMux()} }

func NewStore(basePath string) (*Store, error) {
    if basePath == "" { return nil, fmt.Errorf("storage: basePath required") }
    return &Store{basePath: basePath}, nil
}

func NewDeepSeekClient(apiKey, model string) *DeepSeekClient {
    return &DeepSeekClient{apiKey: apiKey, baseURL: "...", model: model}
}
```

- Return `*T`, not `T` — receivers expect pointers
- `(*T, error)` when init can fail; never read env vars in constructors

---

## 4. Interfaces: Small, Defined Where Consumed

Define interfaces in the **consumer** package (1–3 methods). Producer returns struct.

```go
// Consumer (llm package) defines the interface
type Client interface {
    ChatCompletion(ctx context.Context, msgs []Message, tools []ToolDef) (*Response, error)
}
// Producer returns a concrete type
func NewDeepSeekClient(apiKey, model string) *DeepSeekClient { ... }
```

**Rule:** Accept interfaces, return structs.

---

## 5. HTTP Server (`net/http`, Go 1.22+)

Method-based routing in `http.ServeMux` — no third-party router needed.

```go
mux := http.NewServeMux()
mux.HandleFunc("GET /api/health", handleHealth)
mux.HandleFunc("POST /api/chat", handleChat)

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}
```

- `http.Error(w, msg, code)` for errors; set `Content-Type` before body
- Prefer `json.NewEncoder(w).Encode(v)` over `json.Marshal` + `w.Write`
- Bind `127.0.0.1:0` for ephemeral port; `net.Listen` + `http.Serve` in goroutine

---

## 6. go:embed

```go
// Single file as string
import _ "embed"
//go:embed index.html
var indexHTML string

// Directory with prefix stripping (fs.Sub removes dist/)
//go:embed dist/*
var assets embed.FS

func Assets() fs.FS {
    sub, _ := fs.Sub(assets, "dist") // panics if dist/ missing
    return sub
}
// Usage: http.FileServerFS(Assets())
// Serves /index.html not /dist/index.html
```

---

## 7. SQLite with `database/sql` (No CGo)

Use `ncruces/go-sqlite3` — pure Go, WASM-based driver.

```go
import (
    "database/sql"
    _ "github.com/ncruces/go-sqlite3/driver"
)

db, err := sql.Open("sqlite3", "file:learnit.db")
if err != nil { return fmt.Errorf("storage: open db: %w", err) }
defer db.Close()
```

- Always `CGO_ENABLED=0`; use `QueryRowContext`/`ExecContext` for cancellation
- One `*sql.DB` per app, shared via dependency injection
- `?` placeholders (SQLite syntax), never string interpolation

---

## 8. Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Packages | lowercase, single word, no underscores | `server`, `storage` |
| Exported types/funcs | PascalCase | `FileNode`, `NewServer` |
| Unexported | camelCase | `buildTree`, `handleHealth` |
| Acronyms | All-caps or all-lower, consistent | `URL`, `HTTP` (not `Url`) |
| Interfaces | Single-method: `-er` suffix | `Reader`, `Writer` |
| Constructors | `New` or `New<T>` | `New()`, `NewStore()` |

---

## 9. Performance Tips

```go
// ✅ Pre-allocate slices; use strings.Builder over +=
entries := make([]FileNode, 0, len(files))

// ❌ NEVER defer in a loop — calls stack to function exit
for _, f := range files {
    fd, _ := os.Open(f.Name)
    defer fd.Close() // BUG: all close at return, not iteration end
}

// ✅ Wrap iteration in anonymous function
for _, f := range files {
    func() { fd, _ := os.Open(f.Name); defer fd.Close() }()
}
```

- Pass large structs by pointer; use `sync.Pool` for hot-path allocations

---

## 10. Testing: Table-Driven with `t.Run()`

```go
func TestFormatSize(t *testing.T) {
    tests := []struct {
        name string
        size int64
        want string
    }{
        {"bytes", 42, "42 B"},
        {"kilobytes", 1536, "1.5 KB"},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := FormatSize(tt.size)
            if got != tt.want {
                t.Errorf("FormatSize(%d) = %q; want %q", tt.size, got, tt.want)
            }
        })
    }
}
```

- Name each case — `t.Run` makes failures identifiable; use `t.Errorf` not `t.Fatal`. Benchmarks: `func BenchmarkXxx(b *testing.B)` with `b.ResetTimer()`.

---

## 11. Anti-Patterns

- **No panic in library code** — return errors. Panic only for build-time errors (missing `go:embed` assets) or `log.Fatal` in `main()`
- **No `init()` with side effects** — wire dependencies explicitly in `main()` or constructors
- **No CGo** — `CGO_ENABLED=0`. Use `ncruces/go-sqlite3`, never `mattn/go-sqlite3`
- **No global state** — inject via constructors: `type Store struct { db *sql.DB }`
- **No `defer` in loops** — wrap in anonymous function (see §9)
- **Don't ignore errors** — handle or explicitly discard with `_`

---

## Reference

- [Effective Go](https://go.dev/doc/effective_go) · [Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [Go 1.22 Routing](https://go.dev/blog/routing-enhancements) · [Error Handling (Go 1.13+)](https://go.dev/blog/go1.13-errors)
- [database/sql](https://pkg.go.dev/database/sql) · [go:embed](https://pkg.go.dev/embed)
- [ncruces/go-sqlite3](https://github.com/ncruces/go-sqlite3)
- [Table Driven Tests](https://go.dev/wiki/TableDrivenTests)
