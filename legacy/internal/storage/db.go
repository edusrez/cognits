package storage

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"

	_ "github.com/ncruces/go-sqlite3/driver"
)

type Report struct {
	ID        string   `json:"id"`
	SessionID string   `json:"sessionId"`
	Title     string   `json:"title"`
	Content   string   `json:"content"`
	Summary   string   `json:"summary"`
	Sources   []string `json:"sources"`
	Subagent  string   `json:"subagent"`
	CreatedAt string   `json:"createdAt"`
}

type MessageRow struct {
	ID          int64  `json:"id"`
	SessionID   string `json:"sessionId"`
	Role        string `json:"role"`
	Content     string `json:"content"`
	Reasoning   string `json:"reasoning"`
	ReportID    string `json:"reportId"`
	ReportTitle string `json:"reportTitle"`
	CreatedAt   string `json:"createdAt"`
}

type SessionConfigRow struct {
	SessionID string `json:"sessionId"`
	Provider  string `json:"provider"`
	Model     string `json:"model"`
	Reasoning string `json:"reasoning"`
	AgentID   string `json:"agentId"`
}

type ReportStore struct {
	db *sql.DB
}

const schemaVersion = 1

// baseSchema es idempotente (CREATE IF NOT EXISTS). reports_fts es una tabla FTS5
// de contenido externo: el texto vive solo en reports y los triggers mantienen el
// índice sincronizado, sin duplicar datos ni sincronización manual.
const baseSchema = `
	CREATE TABLE IF NOT EXISTS reports (
		id TEXT PRIMARY KEY,
		session_id TEXT NOT NULL,
		title TEXT NOT NULL,
		content TEXT NOT NULL,
		summary TEXT,
		sources TEXT NOT NULL DEFAULT '[]',
		subagent TEXT NOT NULL DEFAULT 'web_researcher',
		created_at TEXT NOT NULL DEFAULT (datetime('now'))
	);
	CREATE INDEX IF NOT EXISTS idx_reports_session
		ON reports(session_id, created_at);

	CREATE TABLE IF NOT EXISTS messages (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		session_id TEXT NOT NULL,
		role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
		content TEXT NOT NULL,
		reasoning TEXT,
		report_id TEXT,
		report_title TEXT,
		created_at TEXT NOT NULL DEFAULT (datetime('now'))
	);
	CREATE INDEX IF NOT EXISTS idx_messages_session
		ON messages(session_id, created_at);

	CREATE TABLE IF NOT EXISTS session_config (
		session_id TEXT PRIMARY KEY,
		provider TEXT NOT NULL DEFAULT 'deepseek',
		model TEXT NOT NULL DEFAULT 'deepseek-v4-pro',
		reasoning TEXT NOT NULL DEFAULT 'max',
		agent_id TEXT NOT NULL DEFAULT 'orquestador'
	);

	CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
		title, summary, content,
		content='reports',
		content_rowid='rowid',
		tokenize='unicode61'
	);

	CREATE TRIGGER IF NOT EXISTS reports_fts_ai AFTER INSERT ON reports BEGIN
		INSERT INTO reports_fts(rowid, title, summary, content)
		VALUES (new.rowid, new.title, new.summary, new.content);
	END;
	CREATE TRIGGER IF NOT EXISTS reports_fts_ad AFTER DELETE ON reports BEGIN
		INSERT INTO reports_fts(reports_fts, rowid, title, summary, content)
		VALUES ('delete', old.rowid, old.title, old.summary, old.content);
	END;
	CREATE TRIGGER IF NOT EXISTS reports_fts_au AFTER UPDATE ON reports BEGIN
		INSERT INTO reports_fts(reports_fts, rowid, title, summary, content)
		VALUES ('delete', old.rowid, old.title, old.summary, old.content);
		INSERT INTO reports_fts(rowid, title, summary, content)
		VALUES (new.rowid, new.title, new.summary, new.content);
	END;
`

func NewReportStore(dbPath string) (*ReportStore, error) {
	// Los pragmas van en el DSN para que apliquen a CADA conexión del pool:
	// con db.Exec solo los recibía una, y el resto quedaba con busy_timeout=0
	// (SQLITE_BUSY inmediato bajo contención). synchronous=normal es seguro
	// con WAL y evita un fsync por transacción.
	db, err := sql.Open("sqlite3",
		"file:"+dbPath+"?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=synchronous(normal)")
	if err != nil {
		return nil, fmt.Errorf("storage: open db: %w", err)
	}

	// Cada conexión ncruces es una instancia WASM; con un único usuario local
	// bastan pocas (lectores WAL + 1 escritor).
	db.SetMaxOpenConns(4)
	db.SetMaxIdleConns(4)

	if err := migrate(db, dbPath); err != nil {
		db.Close()
		return nil, err
	}

	return &ReportStore{db: db}, nil
}

func migrate(db *sql.DB, dbPath string) error {
	var version int
	if err := db.QueryRow("PRAGMA user_version").Scan(&version); err != nil {
		return fmt.Errorf("storage: read user_version: %w", err)
	}

	if version == 0 {
		var hasReports int
		db.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='reports'`).Scan(&hasReports)
		if hasReports > 0 {
			// DB heredada (pre-versionado): copia de seguridad y limpieza de
			// estructuras incompatibles antes de recrearlas con baseSchema.
			if err := backupDB(db, dbPath); err != nil {
				return err
			}
			if _, err := db.Exec(`DROP TABLE IF EXISTS reports_fts`); err != nil {
				return fmt.Errorf("storage: drop legacy fts: %w", err)
			}
			var hasAPIKey int
			db.QueryRow(`SELECT COUNT(*) FROM pragma_table_info('session_config') WHERE name='api_key'`).Scan(&hasAPIKey)
			if hasAPIKey > 0 {
				if _, err := db.Exec(`ALTER TABLE session_config DROP COLUMN api_key`); err != nil {
					return fmt.Errorf("storage: drop api_key column: %w", err)
				}
			}
		}
	}

	if _, err := db.Exec(baseSchema); err != nil {
		return fmt.Errorf("storage: create schema: %w", err)
	}

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

func backupDB(db *sql.DB, dbPath string) error {
	bak := dbPath + ".bak"
	_ = os.Remove(bak)
	escaped := strings.ReplaceAll(bak, "'", "''")
	if _, err := db.Exec("VACUUM INTO '" + escaped + "'"); err != nil {
		return fmt.Errorf("storage: backup db: %w", err)
	}
	return nil
}

func (rs *ReportStore) Save(r Report) error {
	srcJSON, _ := marshalSources(r.Sources)
	// Upsert explícito en vez de INSERT OR REPLACE: REPLACE borra+inserta sin
	// disparar los triggers de borrado (sin recursive_triggers), lo que
	// corrompería el índice FTS de contenido externo.
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

func (rs *ReportStore) Get(id string) (*Report, error) {
	row := rs.db.QueryRow(
		`SELECT id, session_id, title, content, summary, sources, subagent, created_at
		 FROM reports WHERE id = ?`, id,
	)
	var r Report
	var srcJSON string
	err := row.Scan(&r.ID, &r.SessionID, &r.Title, &r.Content, &r.Summary, &srcJSON, &r.Subagent, &r.CreatedAt)
	if err != nil {
		return nil, fmt.Errorf("storage: get report: %w", err)
	}
	r.Sources = unmarshalSources(srcJSON)
	return &r, nil
}

type ReportSearchResult struct {
	Reports    []Report `json:"reports"`
	Total      int      `json:"total"`
	Page       int      `json:"page"`
	TotalPages int      `json:"totalPages"`
}

func (rs *ReportStore) SearchReports(page, limit int, sort, search string) (*ReportSearchResult, error) {
	if page < 1 {
		page = 1
	}
	if limit < 1 || limit > 50 {
		limit = 10
	}

	var sortSQL string
	switch sort {
	case "date_asc":
		sortSQL = "created_at ASC"
	case "title_asc":
		sortSQL = "title ASC"
	case "title_desc":
		sortSQL = "title DESC"
	default:
		sortSQL = "created_at DESC"
	}

	var whereSQL string
	var args []interface{}
	if search != "" {
		whereSQL = `WHERE title LIKE ? ESCAPE '\' OR summary LIKE ? ESCAPE '\'`
		searchTerm := "%" + escapeLike(search) + "%"
		args = append(args, searchTerm, searchTerm)
	}

	var total int
	err := rs.db.QueryRow(
		"SELECT COUNT(*) FROM reports "+whereSQL, args...,
	).Scan(&total)
	if err != nil {
		return nil, fmt.Errorf("storage: count reports: %w", err)
	}

	totalPages := (total + limit - 1) / limit
	if totalPages == 0 {
		totalPages = 1
	}
	offset := (page - 1) * limit

	queryArgs := append(args, limit, offset)
	rows, err := rs.db.Query(
		`SELECT id, session_id, title, content, summary, sources, subagent, created_at
		 FROM reports `+whereSQL+` ORDER BY `+sortSQL+` LIMIT ? OFFSET ?`,
		queryArgs...,
	)
	if err != nil {
		return nil, fmt.Errorf("storage: search reports: %w", err)
	}
	defer rows.Close()

	var reports []Report
	for rows.Next() {
		var r Report
		var srcJSON string
		if err := rows.Scan(&r.ID, &r.SessionID, &r.Title, &r.Content, &r.Summary, &srcJSON, &r.Subagent, &r.CreatedAt); err != nil {
			return nil, fmt.Errorf("storage: scan report: %w", err)
		}
		r.Sources = unmarshalSources(srcJSON)
		reports = append(reports, r)
	}
	if reports == nil {
		reports = []Report{}
	}

	return &ReportSearchResult{
		Reports:    reports,
		Total:      total,
		Page:       page,
		TotalPages: totalPages,
	}, nil
}

type ReportSearchFTSItem struct {
	Report
	TitleHighlighted string  `json:"titleHighlighted"`
	Score            float64 `json:"score"`
}

type ReportSearchFTSResult struct {
	Reports    []ReportSearchFTSItem `json:"reports"`
	Total      int                   `json:"total"`
	Page       int                   `json:"page"`
	TotalPages int                   `json:"totalPages"`
}

// escapeLike neutraliza los comodines de LIKE en el input del usuario; las
// cláusulas que lo usan deben llevar ESCAPE '\'.
func escapeLike(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, `%`, `\%`)
	return strings.ReplaceAll(s, `_`, `\_`)
}

func buildFTS5Query(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	words := strings.Fields(raw)
	processed := make([]string, 0, len(words))
	for _, w := range words {
		// Dentro de una cadena FTS5 solo la comilla doble es especial: se
		// escapa doblándola. Trim no bastaba — una comilla interior (fo"o)
		// rompía la query y devolvía 500.
		w = strings.Trim(w, `()*`)
		w = strings.ReplaceAll(w, `"`, `""`)
		if len(w) < 1 {
			continue
		}
		processed = append(processed, `"`+w+`"*`)
	}
	if len(processed) == 0 {
		return ""
	}
	return strings.Join(processed, " ")
}

func (rs *ReportStore) SearchReportsFTS(page, limit int, sort, search string) (*ReportSearchFTSResult, error) {
	if page < 1 {
		page = 1
	}
	if limit < 1 || limit > 50 {
		limit = 10
	}

	ftsQuery := buildFTS5Query(search)
	if ftsQuery == "" {
		// Input sin términos útiles (solo comodines/paréntesis): MATCH '' falla.
		return &ReportSearchFTSResult{Reports: []ReportSearchFTSItem{}, Page: page, TotalPages: 1}, nil
	}

	var total int
	err := rs.db.QueryRow(
		`SELECT COUNT(*) FROM reports_fts WHERE reports_fts MATCH ?`,
		ftsQuery,
	).Scan(&total)
	if err != nil {
		return nil, fmt.Errorf("storage: fts count: %w", err)
	}

	totalPages := (total + limit - 1) / limit
	if totalPages == 0 {
		totalPages = 1
	}
	offset := (page - 1) * limit

	var sortSQL string
	switch sort {
	case "date_asc":
		sortSQL = "r.created_at ASC"
	case "title_asc":
		sortSQL = "r.title ASC"
	case "title_desc":
		sortSQL = "r.title DESC"
	default:
		sortSQL = "score"
	}

	query := fmt.Sprintf(`
		SELECT r.id, r.session_id, r.title, r.content, r.summary, r.sources, r.subagent, r.created_at,
			   highlight(reports_fts, 0, '<mark>', '</mark>') AS title_highlighted,
			   bm25(reports_fts, 10.0, 3.0, 1.0) AS score
		FROM reports_fts
		JOIN reports r ON r.rowid = reports_fts.rowid
		WHERE reports_fts MATCH ?
		ORDER BY %s
		LIMIT ? OFFSET ?`, sortSQL)

	rows, err := rs.db.Query(query, ftsQuery, limit, offset)
	if err != nil {
		return nil, fmt.Errorf("storage: fts search: %w", err)
	}
	defer rows.Close()

	var items []ReportSearchFTSItem
	for rows.Next() {
		var r Report
		var titleHighlighted string
		var score float64
		var srcJSON string
		if err := rows.Scan(&r.ID, &r.SessionID, &r.Title, &r.Content, &r.Summary, &srcJSON, &r.Subagent, &r.CreatedAt, &titleHighlighted, &score); err != nil {
			return nil, fmt.Errorf("storage: fts scan: %w", err)
		}
		r.Sources = unmarshalSources(srcJSON)
		items = append(items, ReportSearchFTSItem{
			Report:           r,
			TitleHighlighted: titleHighlighted,
			Score:            score,
		})
	}
	if items == nil {
		items = make([]ReportSearchFTSItem, 0)
	}

	return &ReportSearchFTSResult{
		Reports:    items,
		Total:      total,
		Page:       page,
		TotalPages: totalPages,
	}, nil
}

func (rs *ReportStore) SaveSessionConfig(cfg SessionConfigRow) error {
	_, err := rs.db.Exec(
		`INSERT OR REPLACE INTO session_config (session_id, provider, model, reasoning, agent_id)
		 VALUES (?, ?, ?, ?, ?)`,
		cfg.SessionID, cfg.Provider, cfg.Model, cfg.Reasoning, cfg.AgentID,
	)
	if err != nil {
		return fmt.Errorf("storage: save session config: %w", err)
	}
	return nil
}

func (rs *ReportStore) LoadSessionConfig(sessionID string) (*SessionConfigRow, error) {
	row := rs.db.QueryRow(
		`SELECT session_id, provider, model, reasoning, agent_id
		 FROM session_config WHERE session_id = ?`, sessionID,
	)
	var cfg SessionConfigRow
	err := row.Scan(&cfg.SessionID, &cfg.Provider, &cfg.Model, &cfg.Reasoning, &cfg.AgentID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("storage: load session config: %w", err)
	}
	return &cfg, nil
}

func (rs *ReportStore) DeleteSessionConfig(sessionID string) error {
	_, err := rs.db.Exec(`DELETE FROM session_config WHERE session_id = ?`, sessionID)
	if err != nil {
		return fmt.Errorf("storage: delete session config: %w", err)
	}
	return nil
}

func (rs *ReportStore) DeleteReport(id string) error {
	_, err := rs.db.Exec(`DELETE FROM reports WHERE id = ?`, id)
	if err != nil {
		return fmt.Errorf("storage: delete report: %w", err)
	}
	return nil
}

func (rs *ReportStore) Close() error {
	return rs.db.Close()
}

func (rs *ReportStore) SaveMessages(sessionID string, msgs []MessageRow) error {
	tx, err := rs.db.Begin()
	if err != nil {
		return fmt.Errorf("storage: begin tx: %w", err)
	}
	defer tx.Rollback()

	_, err = tx.Exec("DELETE FROM messages WHERE session_id = ?", sessionID)
	if err != nil {
		return fmt.Errorf("storage: delete old messages: %w", err)
	}

	stmt, err := tx.Prepare(
		`INSERT INTO messages (session_id, role, content, reasoning, report_id, report_title)
		 VALUES (?, ?, ?, ?, ?, ?)`,
	)
	if err != nil {
		return fmt.Errorf("storage: prepare insert: %w", err)
	}
	defer stmt.Close()

	for _, m := range msgs {
		_, err = stmt.Exec(sessionID, m.Role, m.Content, m.Reasoning, m.ReportID, m.ReportTitle)
		if err != nil {
			return fmt.Errorf("storage: insert message: %w", err)
		}
	}

	return tx.Commit()
}

// AppendMessage inserta una sola fila al final del historial. SaveMessages
// reescribe la sesión entera (DELETE+INSERT); para añadir la respuesta del
// asistente al terminar un run basta con esto y la transacción no crece con
// la longitud de la conversación.
func (rs *ReportStore) AppendMessage(sessionID string, m MessageRow) error {
	_, err := rs.db.Exec(
		`INSERT INTO messages (session_id, role, content, reasoning, report_id, report_title)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		sessionID, m.Role, m.Content, m.Reasoning, m.ReportID, m.ReportTitle,
	)
	if err != nil {
		return fmt.Errorf("storage: append message: %w", err)
	}
	return nil
}

func (rs *ReportStore) LoadMessages(sessionID string) ([]MessageRow, error) {
	rows, err := rs.db.Query(
		`SELECT id, session_id, role, content, COALESCE(reasoning,''), COALESCE(report_id,''), COALESCE(report_title,''), created_at
		 FROM messages WHERE session_id = ? ORDER BY id ASC`, sessionID,
	)
	if err != nil {
		return nil, fmt.Errorf("storage: load messages: %w", err)
	}
	defer rows.Close()

	var msgs []MessageRow
	for rows.Next() {
		var m MessageRow
		if err := rows.Scan(&m.ID, &m.SessionID, &m.Role, &m.Content, &m.Reasoning, &m.ReportID, &m.ReportTitle, &m.CreatedAt); err != nil {
			return nil, fmt.Errorf("storage: scan message: %w", err)
		}
		msgs = append(msgs, m)
	}
	return msgs, nil
}

func (rs *ReportStore) DeleteMessagesBySession(sessionID string) error {
	_, err := rs.db.Exec(`DELETE FROM messages WHERE session_id = ?`, sessionID)
	if err != nil {
		return fmt.Errorf("storage: delete messages: %w", err)
	}
	return nil
}

func NewReportID() string {
	b := make([]byte, 8)
	rand.Read(b)
	return "r_" + hex.EncodeToString(b)
}

func marshalSources(sources []string) (string, error) {
	if sources == nil {
		sources = []string{}
	}
	data, err := json.Marshal(sources)
	return string(data), err
}

func unmarshalSources(raw string) []string {
	var sources []string
	_ = json.Unmarshal([]byte(raw), &sources)
	if sources == nil {
		return []string{}
	}
	return sources
}
