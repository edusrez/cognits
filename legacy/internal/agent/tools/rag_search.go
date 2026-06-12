package tools

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/eduardosrez/learnit/internal/rag"
)

type RagSearch struct {
	ragClient *rag.Client
}

func NewRagSearch(ragClient *rag.Client) *RagSearch {
	return &RagSearch{ragClient: ragClient}
}

func (t *RagSearch) Name() string        { return "rag_search" }
func (t *RagSearch) Description() string { return "Busca informacion en la base de conocimiento interna (informes de investigacion y documentacion indexada). Devuelve fragmentos relevantes con su fuente y puntuacion de similitud." }

func (t *RagSearch) Schema() json.RawMessage {
	return json.RawMessage(`{
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "Texto de busqueda semantica"},
			"max_results": {"type": "integer", "description": "Maximo de fragmentos a devolver (por defecto 10)"}
		},
		"required": ["query"]
	}`)
}

func (t *RagSearch) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var a struct {
		Query      string `json:"query"`
		MaxResults int    `json:"max_results"`
	}
	if err := json.Unmarshal(args, &a); err != nil {
		return toolError(fmt.Sprintf("invalid args: %s", err.Error())), nil
	}

	results, err := t.ragClient.Search(ctx, a.Query, a.MaxResults)
	if err != nil {
		return toolError(fmt.Sprintf("rag search error: %s", err.Error())), nil
	}

	if len(results) == 0 {
		return `{"found": false, "results": []}`, nil
	}

	type resultJSON struct {
		Text       string  `json:"text"`
		ReportID   string  `json:"report_id"`
		SourceType string  `json:"source_type"`
		Topic      string  `json:"topic"`
		Distance   float64 `json:"distance"`
	}

	out := make([]resultJSON, len(results))
	for i, r := range results {
		out[i] = resultJSON{
			Text:       r.Text,
			ReportID:   r.ReportID,
			SourceType: r.SourceType,
			Topic:      r.Topic,
			Distance:   r.Distance,
		}
	}

	data, _ := json.Marshal(map[string]any{
		"found":   true,
		"results": out,
	})
	return string(data), nil
}

func toolError(msg string) string {
	data, _ := json.Marshal(map[string]string{"error": msg})
	return string(data)
}
