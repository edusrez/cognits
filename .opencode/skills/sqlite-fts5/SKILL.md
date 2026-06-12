---
name: sqlite-fts5
description: |
  SQLite FTS5 full-text search patterns with `ncruces/go-sqlite3` (WASM driver,
  no CGo). Covers external content tables, triggers, BM25 relevance scoring,
  `highlight()` snippets, prefix-matching queries, schema migration with
  `PRAGMA user_version`, DSN pragmas, and connection pool sizing.
  Trigger phrases: FTS5, full-text search, SQLite search, BM25, highlight,
  reports_fts, external content table, VACUUM INTO, content_rowid,
  INSERT OR REPLACE FTS, recursive_triggers, ON CONFLICT DO UPDATE, rebuild fts,
  busy_timeout, journal_mode WAL, synchronous normal, ncruces driver, wasm sqlite.
  Use when adding/modifying tables that use FTS5, debugging FTS index corruption,
  changing report schema, or writing SQLite DSN strings with `_pragma=` parameters.
target: ncruces/go-sqlite3 v0.19+, SQLite 3.43+
---
# SQLite FTS5 Full-Text Search

Extends [go-conventions](../go-conventions/SKILL.md). Read that first for
general Go + SQLite patterns (constructors, error wrapping, `database/sql`
skeleton). This skill covers FTS5-specific patterns only.

## When to Use

- Creating a virtual table with `USING fts5(content=...)`
- Writing triggers to keep an FTS index in sync with a real table
- Searching text with `MATCH` and BM25 relevance scoring
- Returning highlighted search snippets via `highlight()`
- Building FTS5 queries from user input (prefix-matching)
- Migrating a schema that includes FTS5 tables
- Writing SQLite DSN strings with `_pragma=` parameters for WASM driver
- Debugging FTS index corruption or orphaned rows

---

## 1. External Content Tables

FTS5 "external content" means text lives **only** in the real table. The
FTS virtual table stores just the token index, referencing rows by `rowid`.
This avoids data duplication and keeps a single source of truth.

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
    title, summary, content,
    content='reports',        -- real table
    content_rowid='rowid',    -- join column (default: rowid)
    tokenize='unicode61'      -- unicode-aware tokenizer
);
```

**How it works:**

- `content='reports'` — FTS5 reads text from the `reports` table, not from
  shadow tables. No data is stored inside the FTS index.
- `content_rowid='rowid'` — the column in `reports` that links to FTS5's
  internal rowid. Usually `rowid` (the implicit SQLite primary key).
- `tokenize='unicode61'` — the default Unicode tokenizer (case-folding,
  diacritic removal). Use `porter` for stemming, `trigram` for
  substring matching, or `unicode61 remove_diacritics 0` to preserve
  diacritics.

**Column order matters.** FTS5 column indices (0, 1, 2, …) are used by
`highlight()` and `bm25()` weighting. Keep them stable across migrations
unless you also update all queries.

---

## 2. Triggers for FTS Sync

External content tables need **three triggers** to stay synchronized. Without
them, the FTS index sees stale or missing data.

```sql
-- After INSERT: add new row to FTS index
CREATE TRIGGER IF NOT EXISTS reports_fts_ai AFTER INSERT ON reports BEGIN
    INSERT INTO reports_fts(rowid, title, summary, content)
    VALUES (new.rowid, new.title, new.summary, new.content);
END;

-- After DELETE: remove row from FTS index (special 'delete' command)
CREATE TRIGGER IF NOT EXISTS reports_fts_ad AFTER DELETE ON reports BEGIN
    INSERT INTO reports_fts(reports_fts, rowid, title, summary, content)
    VALUES ('delete', old.rowid, old.title, old.summary, old.content);
END;

-- After UPDATE: delete old entry + insert new entry
CREATE TRIGGER IF NOT EXISTS reports_fts_au AFTER UPDATE ON reports BEGIN
    INSERT INTO reports_fts(reports_fts, rowid, title, summary, content)
    VALUES ('delete', old.rowid, old.title, old.summary, old.content);
    INSERT INTO reports_fts(rowid, title, summary, content)
    VALUES (new.rowid, new.title, new.summary, new.content);
END;
```

**Key details:**

- The `AFTER DELETE` and `AFTER UPDATE` triggers use the magic string
  `'delete'` as the first column value — this tells FTS5 to remove the
  entry identified by the subsequent values.
- In `AFTER UPDATE`, you must explicitly list `new.column` values so the
  index reflects the new state. The `'delete'` command removes the old row;
  the second `INSERT` adds the updated one.
- **All three triggers reference `old.rowid` / `new.rowid`.**
  This ties the FTS entry to the real table's rowid, which is the
  `content_rowid` column from the virtual table definition.

⚠️ **Without `recursive_triggers` enabled, `INSERT OR REPLACE` does NOT fire
the `AFTER DELETE` trigger** (see §3). The triggers rely on normal
`DELETE`/`UPDATE` statements to fire.

---

## 3. The `INSERT OR REPLACE` Trap

> **CRITICAL:** NEVER use `INSERT OR REPLACE` on a table that has an
> external content FTS5 index.

**Why it corrupts the index:**

`REPLACE` is implemented as `DELETE` + `INSERT` internally. However,
**without `PRAGMA recursive_triggers = ON`**, the `DELETE` half does
**not** fire the `AFTER DELETE` trigger. Result: the old row's FTS entry
is never removed — it becomes an **orphaned entry** in the FTS index.

These orphaned entries:
- Point to `rowid`s that no longer exist in the real table
- Inflate `COUNT(*)` results from FTS queries
- Cause `JOIN` queries to return rows with `NULL` real-table columns
- Accumulate silently over time

### ✅ Correct: `ON CONFLICT DO UPDATE`

```go
_, err := rs.db.Exec(
    `INSERT INTO reports (id, session_id, title, content, summary, sources, subagent)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
        session_id = excluded.session_id,
        title      = excluded.title,
        content    = excluded.content,
        summary    = excluded.summary,
        sources    = excluded.sources,
        subagent   = excluded.subagent`,
    r.ID, r.SessionID, r.Title, r.Content, r.Summary, srcJSON, r.Subagent,
)
```

- `excluded.column` refers to the value from the `VALUES` clause
- Explicit column list — avoids blind overwrite
- The `UPDATE` half fires `AFTER UPDATE`, which properly deletes + re-inserts
  the FTS entry

### ❌ Wrong: `INSERT OR REPLACE`

```go
// NEVER do this on an external content table
db.Exec(`INSERT OR REPLACE INTO reports (id, title, content) VALUES (?, ?, ?)`, ...)
// FTS index now has orphaned entries for every replaced row
```

### ❌ Also wrong: `UPSERT` using `REPLACE`

```sql
-- This is just syntactic sugar for INSERT OR REPLACE
REPLACE INTO reports (id, title) VALUES (?, ?);
```

**The only exception:** tables **without** external FTS5 content can safely
use `INSERT OR REPLACE`. Example from this project:

```go
// session_config has no FTS index → INSERT OR REPLACE is safe
_, err := rs.db.Exec(
    `INSERT OR REPLACE INTO session_config (session_id, provider, model, reasoning, agent_id)
     VALUES (?, ?, ?, ?, ?)`,
    cfg.SessionID, cfg.Provider, cfg.Model, cfg.Reasoning, cfg.AgentID,
)
```

---

## 4. BM25 Scoring with Weighted Columns

BM25 (Best Match 25) is a probabilistic relevance function. FTS5 exposes it
via the `bm25()` auxiliary function.

```sql
SELECT
    r.id, r.title,
    highlight(reports_fts, 0, '<mark>', '</mark>') AS title_highlighted,
    bm25(reports_fts, 10.0, 3.0, 1.0) AS score
FROM reports_fts
JOIN reports r ON r.rowid = reports_fts.rowid
WHERE reports_fts MATCH ?
ORDER BY score
```

**Weight per column:** `bm25(reports_fts, w0, w1, w2, ...)` — one weight
per FTS5 column, in declaration order. Higher weight → more impact on score.

| Column index | Column | Weight | Rationale |
|---|---|---|---|
| 0 | `title` | 10.0 | Matches in title = strong relevance signal |
| 1 | `summary` | 3.0 | Summary matches are meaningful but less precise |
| 2 | `content` | 1.0 | Full-text body matches have baseline weight |

**Default sort:** `ORDER BY score` when searching. For non-search listings
(date browsing), fall back to `ORDER BY created_at DESC`.

**Note on joins:** Always `JOIN ... ON r.rowid = reports_fts.rowid`.
The FTS5 table's `rowid` matches the real table's `rowid` (as declared in
`content_rowid='rowid'`).

---

## 5. `highlight()` for Search Snippets

The `highlight()` auxiliary function wraps matching terms in tags.

```sql
highlight(reports_fts, column_index, '<mark>', '</mark>')
```

- **First argument:** the FTS table name
- **Second argument:** the **column index** (0-based, in FTS5 column order)
- **Third argument:** opening tag (HTML or any string)
- **Fourth argument:** closing tag

```go
// In Go:
var titleHighlighted string
var score float64
row.Scan(&r.ID, &r.SessionID, &r.Title, ..., &titleHighlighted, &score)
// titleHighlighted contains: "Learning <mark>Rust</mark> for Beginners"
```

**Usage in UI:** Render the highlighted string as HTML with `dangerouslySetInnerHTML`
(or SolidJS equivalent) so `<mark>` tags are rendered as visual highlights.

**Common pattern:**

```sql
SELECT
    highlight(reports_fts, 0, '<mark>', '</mark>') AS title_highlighted,
    highlight(reports_fts, 2, '<mark>', '</mark>') AS content_snippet
FROM reports_fts
WHERE reports_fts MATCH ?
LIMIT 10
```

Column index `0` = `title`, `1` = `summary`, `2` = `content` (matching the
`CREATE VIRTUAL TABLE` declaration order).

---

## 6. Prefix-Matching FTS Queries

FTS5 supports `*` as a prefix wildcard. User input needs to be converted
from plain text to prefix-match syntax.

```go
func buildFTS5Query(raw string) string {
    raw = strings.TrimSpace(raw)
    if raw == "" {
        return ""
    }
    words := strings.Fields(raw)
    processed := make([]string, 0, len(words))
    for _, w := range words {
        w = strings.Trim(w, `"()*`)     // strip existing FTS syntax characters
        if len(w) < 1 {
            continue
        }
        processed = append(processed, `"`+w+`"*`)   // wrap in quotes + prefix
    }
    if len(processed) == 0 {
        return raw + "*"                 // single-character fallback
    }
    return strings.Join(processed, " ")
}
```

**How it works:**

| User input | Generated FTS query | Matches |
|---|---|---|
| `rust` | `"rust"*` | rust, rustacean, rustc, rusting |
| `learn rust` | `"learn"* "rust"*` | learning rust, learned rustacean |
| `"hello world"` | `"hello world"*` (if no space-tokenized) | exact phrase prefix |

**Safety:** Strip characters `"`, `(`, `)`, `*` from user input before
wrapping. User-supplied `*` or `"` would otherwise produce invalid or
unexpected FTS5 syntax.

**Usage in search:**

```go
ftsQuery := buildFTS5Query(search)
rows, err := db.Query(
    `SELECT ... FROM reports_fts WHERE reports_fts MATCH ?`,
    ftsQuery,
)
```

**Fallback to LIKE:** When the search string is empty or FTS5 returns zero
results, consider falling back to a standard `LIKE` query:

```go
if search != "" {
    // FTS path
    rs.SearchReportsFTS(page, limit, sort, search)
} else {
    rs.SearchReports(page, limit, sort, search)
}
```

---

## 7. Schema Migration with `PRAGMA user_version`

Use `PRAGMA user_version` (an integer stored in the database header) to
track schema version. This is the standard SQLite migration mechanism.

```go
const schemaVersion = 1

func migrate(db *sql.DB, dbPath string) error {
    // 1. Read current version (0 = unversioned/new)
    var version int
    if err := db.QueryRow("PRAGMA user_version").Scan(&version); err != nil {
        return fmt.Errorf("storage: read user_version: %w", err)
    }

    // 2. Handle legacy databases (version == 0 with existing tables)
    if version == 0 {
        var hasReports int
        db.QueryRow(`SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='reports'`).Scan(&hasReports)
        if hasReports > 0 {
            backupDB(db, dbPath)       // safety net before destructive ops
            db.Exec(`DROP TABLE IF EXISTS reports_fts`)  // clean up legacy
        }
    }

    // 3. Apply base schema (idempotent: CREATE IF NOT EXISTS)
    if _, err := db.Exec(baseSchema); err != nil {
        return fmt.Errorf("storage: create schema: %w", err)
    }

    // 4. Rebuild FTS index if version bumped
    if version < schemaVersion {
        if _, err := db.Exec(`INSERT INTO reports_fts(reports_fts) VALUES('rebuild')`); err != nil {
            return fmt.Errorf("storage: rebuild fts: %w", err)
        }
        if _, err := db.Exec(fmt.Sprintf("PRAGMA user_version = %d", schemaVersion)); err != nil {
            return fmt.Errorf("storage: set user_version: %w", err)
        }
    }

    return nil
}
```

**Migration checklist:**

| Step | Purpose |
|---|---|
| `PRAGMA user_version` | Read current schema version |
| Check `sqlite_master` | Detect pre-versioned legacy DBs |
| `VACUUM INTO` | Backup before destructive schema changes |
| `CREATE IF NOT EXISTS` | Idempotent base schema |
| `INSERT INTO fts_table(fts_table) VALUES('rebuild')` | Rebuild FTS index from real table |
| `PRAGMA user_version = N` | Bump version after migration |

**FTS rebuild:** `INSERT INTO reports_fts(reports_fts) VALUES('rebuild')`
is an FTS5 command that clears the entire FTS index and re-tokenizes all
text from the content table. Essential after:
- Adding/changing columns in the FTS5 virtual table
- Migrating from a non-FTS5 schema
- Fixing FTS index corruption

**Backup with VACUUM INTO:**

```go
func backupDB(db *sql.DB, dbPath string) error {
    bak := dbPath + ".bak"
    os.Remove(bak)
    escaped := strings.ReplaceAll(bak, "'", "''")
    if _, err := db.Exec("VACUUM INTO '" + escaped + "'"); err != nil {
        return fmt.Errorf("storage: backup db: %w", err)
    }
    return nil
}
```

- `VACUUM INTO` creates a minimal, defragmented copy
- Escape single quotes in path before interpolation
- Remove existing `.bak` to avoid conflicts

---

## 8. DSN Pragmas for WASM Driver

**Always set pragmas in the DSN, never via `db.Exec()`.**

```go
// ✅ Correct: pragmas in DSN apply to EVERY connection in the pool
db, err := sql.Open("sqlite3",
    "file:"+dbPath+"?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=synchronous(normal)")
```

```go
// ❌ Wrong: only ONE connection receives the pragma
db, _ := sql.Open("sqlite3", "file:mydb.db")
db.Exec("PRAGMA busy_timeout = 5000")  // other connections still have busy_timeout=0
```

**The three essential pragmas:**

| Pragma | Value | Why |
|---|---|---|
| `busy_timeout` | `5000` | Wait 5s instead of immediate `SQLITE_BUSY` on lock |
| `journal_mode` | `WAL` | Write-Ahead Log: concurrent readers + 1 writer, no read blocking |
| `synchronous` | `NORMAL` | Safe with WAL, avoids `fsync` per transaction (huge perf gain) |

**DSN format:** `file:path?_pragma=key(value)&_pragma=key(value)`

- `_pragma=` is a SQLite URI parameter understood by the driver
- Multiple pragmas separated by `&`
- The `ncruces/go-sqlite3` driver processes these on every connection open

**Never omit `busy_timeout` with WAL.** Under WAL, writers may block on
a busy database. Without `busy_timeout`, the default is 0 → immediate
`SQLITE_BUSY` error → transaction failed. With WAL + `busy_timeout(5000)`,
the writer waits up to 5 seconds for the lock.

---

## 9. Connection Pool for WASM Driver

Each connection with `ncruces/go-sqlite3` is a **WASM instance**.
Single-user local apps need very few connections.

```go
db.SetMaxOpenConns(4)  // max 4 WASM instances
db.SetMaxIdleConns(4)  // keep all open to avoid WASM instantiation cost
```

**Rationale:**

- WAL mode allows any number of concurrent readers
- Only one writer at a time (SQLite limitation)
- 4 connections cover: 1 writer + 3 concurrent readers
- Local single-user app → no high-concurrency scaling needed
- Keeping idle connections alive avoids WASM re-instantiation cost
- `SetMaxIdleConns == SetMaxOpenConns` means no connections are ever closed
  and reopened

**Don't overprovision.** Each WASM instance has memory overhead. 4 is the
sweet spot for this type of app. Cloud databases with hundreds of concurrent
users would need more, but `ncruces/go-sqlite3` is not designed for that
scenario.

---

## 10. Upsert for Reports

The upsert pattern — insert a new row or update if it exists — must use
`ON CONFLICT DO UPDATE` for external content tables (see §3 for why
`INSERT OR REPLACE` is forbidden).

```go
func (rs *ReportStore) Save(r Report) error {
    srcJSON, _ := marshalSources(r.Sources)
    _, err := rs.db.Exec(
        `INSERT INTO reports (id, session_id, title, content, summary, sources, subagent)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
            session_id = excluded.session_id,
            title      = excluded.title,
            content    = excluded.content,
            summary    = excluded.summary,
            sources    = excluded.sources,
            subagent   = excluded.subagent`,
        r.ID, r.SessionID, r.Title, r.Content, r.Summary, srcJSON, r.Subagent,
    )
    if err != nil {
        return fmt.Errorf("storage: save report: %w", err)
    }
    return nil
}
```

**Rules:**

| Pattern | Use |
|---|---|
| `INSERT ... ON CONFLICT DO UPDATE SET col = excluded.col` | Tables with FTS5 external content |
| `INSERT OR REPLACE` | Tables without FTS5 index |

**`excluded` keyword:** Refers to the values from the `VALUES` clause —
the row that would have been inserted if the conflict hadn't occurred.

**Explicit column list:** Always list every updatable column explicitly
in the `SET` clause. Don't use `DO UPDATE SET *` — it's not valid SQL.

**JSON columns:** Marshal Go slices/maps to JSON strings before storing.
Use `json.Marshal` for writes, `json.Unmarshal` for reads:

```go
func marshalSources(sources []string) (string, error) {
    if sources == nil {
        sources = []string{}
    }
    data, err := json.Marshal(sources)
    return string(data), err
}
```

---

## 11. Full FTS Search Query Pattern

Putting it all together — the complete search query:

```go
func (rs *ReportStore) SearchReportsFTS(page, limit int, sort, search string) (*ReportSearchFTSResult, error) {
    ftsQuery := buildFTS5Query(search)

    // Get total matching count from FTS
    var total int
    rs.db.QueryRow(
        `SELECT COUNT(*) FROM reports_fts WHERE reports_fts MATCH ?`,
        ftsQuery,
    ).Scan(&total)

    offset := (page - 1) * limit

    query := fmt.Sprintf(`
        SELECT r.id, r.session_id, r.title, r.content, r.summary,
               r.sources, r.subagent, r.created_at,
               highlight(reports_fts, 0, '<mark>', '</mark>') AS title_highlighted,
               bm25(reports_fts, 10.0, 3.0, 1.0) AS score
        FROM reports_fts
        JOIN reports r ON r.rowid = reports_fts.rowid
        WHERE reports_fts MATCH ?
        ORDER BY %s
        LIMIT ? OFFSET ?`, sortSQL)

    rows, err := rs.db.Query(query, ftsQuery, limit, offset)
    // ... scan rows: 8 report columns + title_highlighted + score
}
```

**Points to note:**

- `COUNT(*)` runs against `reports_fts` directly (fast, no join needed)
- The `JOIN` uses `r.rowid = reports_fts.rowid` — the binding from
  `content_rowid='rowid'`
- `highlight()` returns the first FTS column (title) with matches wrapped
- `bm25()` returns a float64 score; sort by it for relevance ranking
- `sortSQL` fallback: `ORDER BY score` when searching, `ORDER BY created_at DESC`
  when browsing

---

## 12. Delete Pattern for FTS Tables

Deleting from the real table automatically cleans up FTS via triggers:

```go
func (rs *ReportStore) DeleteReport(id string) error {
    _, err := rs.db.Exec(`DELETE FROM reports WHERE id = ?`, id)
    // The AFTER DELETE trigger (reports_fts_ad) fires automatically
    if err != nil {
        return fmt.Errorf("storage: delete report: %w", err)
    }
    return nil
}
```

No manual FTS cleanup needed — the trigger handles it. This is why external
content tables are preferred over content tables: a single `DELETE` keeps
everything in sync.

---

## 13. Anti-Patterns

| ❌ Never | ✅ Instead |
|---|---|
| `INSERT OR REPLACE` on external content tables | `INSERT ... ON CONFLICT DO UPDATE` |
| `mattn/go-sqlite3` (requires CGo) | `ncruces/go-sqlite3` (pure Go, WASM) |
| `db.Exec("PRAGMA ...")` for connection settings | DSN with `_pragma=key(value)` |
| `REPLACE INTO reports ...` | `INSERT ... ON CONFLICT DO UPDATE` |
| Skip FTS rebuild after schema changes | `INSERT INTO fts_table(fts_table) VALUES('rebuild')` |
| `sql.Open("sqlite3", "file:db.db")` without pragmas | Include `busy_timeout`, `journal_mode(WAL)`, `synchronous(normal)` |
| Omit `SetMaxOpenConns` / `SetMaxIdleConns` | Set both to 4 for WASM driver |
| Use `content=` tables without triggers | Always write INSERT/UPDATE/DELETE triggers |
| Use `[]interface{}` for query args | Use concrete slices `[]any` with `...` spread |
| `content_rowid` mismatch between FTS definition and trigger `rowid` references | Keep them consistent (both use `rowid`) |
| Destructive migrations without backup | `VACUUM INTO 'file.bak'` before DROP/ALTER |

**Connection pool anti-patterns:**

```go
// ❌ Too few: serializes all access
db.SetMaxOpenConns(1)

// ❌ Too many: wasteful WASM instances
db.SetMaxOpenConns(50)

// ✅ Just right for WASM single-user
db.SetMaxOpenConns(4)
db.SetMaxIdleConns(4)
```

---

## Reference

- [SQLite FTS5 Documentation](https://www.sqlite.org/fts5.html)
- [FTS5 External Content Tables](https://www.sqlite.org/fts5.html#external_content_and_contentless_tables)
- [FTS5 Auxiliary Functions (highlight, bm25)](https://www.sqlite.org/fts5.html#the_highlight_function)
- [FTS5 `INSERT` Commands (including 'delete' and 'rebuild')](https://www.sqlite.org/fts5.html#the_insert_command)
- [SQLite PRAGMA Statements](https://www.sqlite.org/pragma.html)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [SQLite URI Filenames](https://www.sqlite.org/uri.html)
- [ncruces/go-sqlite3](https://github.com/ncruces/go-sqlite3)
- [SQLite `ON CONFLICT` Clause](https://www.sqlite.org/lang_conflict.html)
- [Go `database/sql` Package](https://pkg.go.dev/database/sql)
