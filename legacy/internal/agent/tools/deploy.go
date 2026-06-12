package tools

import (
	"context"
	"encoding/json"
	"log"
	"strings"

	"github.com/eduardosrez/learnit/internal/agent"
	"github.com/eduardosrez/learnit/internal/llm"
	"github.com/eduardosrez/learnit/internal/rag"
	"github.com/eduardosrez/learnit/internal/storage"
)

type deploySubagentArgs struct {
	Type  string `json:"type"`
	Query string `json:"query"`
}

type DeploySubagent struct {
	LLMClient   llm.Client
	ReportStore *storage.ReportStore
	Subagents   map[string]*agent.AgentConfig
	SessionID   func() string
	Emit        func(agent.Event)
	RagClient   *rag.Client
}

func (t *DeploySubagent) Name() string {
	return "deploy_subagent"
}

func (t *DeploySubagent) Description() string {
	return "Deploy a subagent to perform research or analysis. Use web_researcher for web research with sources."
}

func (t *DeploySubagent) Schema() json.RawMessage {
	return json.RawMessage(`{
		"type": "object",
		"properties": {
			"type": {"type": "string", "enum": ["web_researcher"]},
			"query": {"type": "string", "description": "Research task description"}
		},
		"required": ["type", "query"]
	}`)
}

func (t *DeploySubagent) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var parsed deploySubagentArgs
	if err := json.Unmarshal(args, &parsed); err != nil {
		errJSON, _ := json.Marshal(map[string]string{"error": "invalid args: " + err.Error()})
		return string(errJSON), nil
	}

	cfg, ok := t.Subagents[parsed.Type]
	if !ok {
		errJSON, _ := json.Marshal(map[string]string{"error": "unknown subagent: " + parsed.Type})
		return string(errJSON), nil
	}

	sessionID := ""
	if t.SessionID != nil {
		sessionID = t.SessionID()
	}

	reportID := storage.NewReportID()

	orchestrator := agent.New(*cfg, t.LLMClient)

	emit := func(ev agent.Event) {
		if t.Emit == nil {
			return
		}
		switch ev.Type {
		case "reasoning":
			t.Emit(agent.Event{
				Type: "tool_progress",
				Data: map[string]interface{}{"message": "Pensando..."},
			})
			return
		case "token":
			return
		case "tool_start":
			data, ok := ev.Data.(map[string]interface{})
			tool := ""
			if ok && data != nil {
				tool, _ = data["tool"].(string)
			}
			msg := "Buscando en la Web"
			if tool == "tinyfish_fetch_content" {
				msg = "Leyendo Resultados"
			}
			t.Emit(agent.Event{
				Type: "tool_progress",
				Data: map[string]interface{}{"message": msg},
			})
		default:
			t.Emit(ev)
		}
	}

	content, err := orchestrator.Run(ctx, []llm.Message{
		{Role: llm.RoleUser, Content: parsed.Query},
	}, emit)
	if err != nil {
		// Cancelado: sin informe, sin indexado, sin subagent_end. El bucle del
		// agente padre corta limpio en su siguiente check de ctx.
		if ctx.Err() != nil {
			return "", err
		}
		// Fallo real: limpiar el banner de estado y devolver el error al
		// orquestador como resultado de tool, sin crear un informe basura.
		if t.Emit != nil {
			t.Emit(agent.Event{
				Type: "tool_progress",
				Data: map[string]interface{}{"message": ""},
			})
		}
		errJSON, _ := json.Marshal(map[string]string{"error": "subagent failed: " + err.Error()})
		return string(errJSON), nil
	}

	title := extractTitle(content, parsed.Query)

	report := storage.Report{
		ID:        reportID,
		SessionID: sessionID,
		Title:     title,
		Content:   content,
		Summary:   extractSummary(content),
		Sources:   []string{},
		Subagent:  parsed.Type,
	}

	if t.ReportStore != nil {
		if err := t.ReportStore.Save(report); err != nil {
			log.Printf("deploy: save report %s: %v", reportID, err)
		}
	}

	if t.RagClient != nil && content != "" {
		chunks := rag.SplitMarkdown(content, reportID, title)
		if len(chunks) > 0 {
			if n, err := t.RagClient.Index(ctx, chunks); err != nil {
				log.Printf("deploy: index chunks (report %s): %v", reportID, err)
			} else {
				log.Printf("deploy: indexed %d chunks for report %s", n, reportID)
			}
		}
	}

	if t.Emit != nil {
		t.Emit(agent.Event{
			Type: "subagent_end",
			Data: map[string]interface{}{
				"reportId": reportID,
				"title":    title,
				"summary":  report.Summary,
			},
		})
	}

	result := map[string]interface{}{
		"reportId": reportID,
		"title":    title,
		"summary":  report.Summary,
		"content":  content,
	}
	resultJSON, _ := json.Marshal(result)
	return string(resultJSON), nil
}

func extractTitle(content string, fallback string) string {
	lines := strings.Split(content, "\n")
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "# ") {
			return strings.TrimPrefix(trimmed, "# ")
		}
	}
	if runes := []rune(fallback); len(runes) > 80 {
		return string(runes[:80]) + "..."
	}
	return fallback
}

func extractSummary(content string) string {
	lines := strings.Split(content, "\n")
	var summary strings.Builder
	inContent := false
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			if summary.Len() > 0 {
				break
			}
			continue
		}
		if strings.HasPrefix(trimmed, "#") {
			if inContent {
				break
			}
			inContent = true
			continue
		}
		if inContent && !strings.HasPrefix(trimmed, "**") {
			summary.WriteString(trimmed)
			summary.WriteString(" ")
		}
		if summary.Len() > 200 {
			break
		}
	}
	return strings.TrimSpace(summary.String())
}
