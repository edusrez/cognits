package server

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/eduardosrez/learnit/internal/agent"
)

func (s *Server) handleSessionStream(w http.ResponseWriter, r *http.Request) {
	sid := r.PathValue("id")

	s.agentMu.Lock()
	sa, exists := s.activeAgents[sid]
	if !exists {
		s.agentMu.Unlock()
		s.sendMessagesSnapshot(w, r, sid)
		return
	}
	// Suscripción y snapshot son atómicos: ningún evento puede quedar a la vez
	// dentro del snapshot y pendiente en el canal (duplicaría tokens).
	ch, snap := sa.SubscribeWithSnapshot()
	s.agentMu.Unlock()
	defer sa.Unsubscribe(ch)

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	msgSnapshot := make([]map[string]interface{}, 0, len(snap.Messages))
	for _, m := range snap.Messages {
		msgSnapshot = append(msgSnapshot, map[string]interface{}{
			"role":        m.Role,
			"content":     m.Content,
			"reasoning":   m.Reasoning,
			"reportId":    m.ReportID,
			"reportTitle": m.ReportTitle,
		})
	}
	historyData, _ := json.Marshal(map[string]interface{}{
		"messages":        msgSnapshot,
		"toolStatus":      snap.ToolStatus,
		"liveContent":     snap.LiveContent,
		"liveReasoning":   snap.LiveReasoning,
		"liveReportId":    snap.LiveReportID,
		"liveReportTitle": snap.LiveReportTitle,
		"agentActive":     true,
	})

	fmt.Fprintf(w, "event: history\ndata: %s\n\n", string(historyData))
	flusher.Flush()

	writeEvent := func(eventType string, data interface{}) {
		jsonData, _ := json.Marshal(data)
		if eventType != "" {
			fmt.Fprintf(w, "event: %s\n", eventType)
		}
		fmt.Fprintf(w, "data: %s\n\n", string(jsonData))
		flusher.Flush()
	}

	forward := func(ev agent.Event) {
		switch ev.Type {
		case "token":
			writeEvent("", map[string]interface{}{
				"choices": []map[string]interface{}{
					{"delta": map[string]interface{}{"content": ev.Data}},
				},
			})
		case "reasoning":
			writeEvent("reasoning", map[string]interface{}{"content": ev.Data})
		case "error":
			writeEvent("error", map[string]interface{}{"message": ev.Data})
		case "tool_start", "tool_end", "tool_progress", "subagent_end", "usage":
			writeEvent(ev.Type, ev.Data)
		}
	}

	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case ev := <-ch:
			forward(ev)
		case <-sa.Done:
			// Drenar los eventos pendientes antes de cerrar.
			for {
				select {
				case ev := <-ch:
					forward(ev)
				default:
					writeEvent("done", nil)
					return
				}
			}
		case <-r.Context().Done():
			return
		case <-ticker.C:
			fmt.Fprintf(w, ": keepalive\n\n")
			flusher.Flush()
		}
	}
}

func (s *Server) sendMessagesSnapshot(w http.ResponseWriter, r *http.Request, sid string) {
	if s.reportStore == nil {
		http.Error(w, "db not available", http.StatusInternalServerError)
		return
	}

	rows, err := s.reportStore.LoadMessages(sid)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	messages := make([]map[string]interface{}, 0, len(rows))
	for _, row := range rows {
		messages = append(messages, map[string]interface{}{
			"role":        row.Role,
			"content":     row.Content,
			"reasoning":   row.Reasoning,
			"reportId":    row.ReportID,
			"reportTitle": row.ReportTitle,
		})
	}

	historyData, _ := json.Marshal(map[string]interface{}{"messages": messages})

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	fmt.Fprintf(w, "event: history\ndata: %s\n\n", string(historyData))
	fmt.Fprintf(w, "event: done\ndata: {}\n\n")
}
