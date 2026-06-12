package server

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/eduardosrez/learnit/internal/agent"
	"github.com/eduardosrez/learnit/internal/agent/subagents"
	agenttools "github.com/eduardosrez/learnit/internal/agent/tools"
	"github.com/eduardosrez/learnit/internal/llm"
	"github.com/eduardosrez/learnit/internal/storage"
	"github.com/eduardosrez/learnit/internal/tinyfish"
	"github.com/eduardosrez/learnit/internal/tools"
)

const (
	defaultModel              = "deepseek-v4-pro"
	defaultResearcherMaxSteps = 15
	orchestratorMaxSteps      = 25
)

type chatIncomingMessage struct {
	Role        string `json:"role"`
	Content     string `json:"content"`
	Reasoning   string `json:"reasoning"`
	ReportID    string `json:"reportId"`
	ReportTitle string `json:"reportTitle"`
}

type chatRequest struct {
	Messages []chatIncomingMessage `json:"messages"`
}

func (s *Server) handleChat(w http.ResponseWriter, r *http.Request) {
	cfg := s.configSnapshot()
	if cfg == nil {
		http.Error(w, "config not available", http.StatusInternalServerError)
		return
	}
	if cfg.LLMApiKey == "" {
		http.Error(w, "API key not configured", http.StatusUnauthorized)
		return
	}

	var chatReq chatRequest
	if err := json.NewDecoder(r.Body).Decode(&chatReq); err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}

	sid := r.URL.Query().Get("sessionId")
	if sid == "" {
		http.Error(w, "sessionId required", http.StatusBadRequest)
		return
	}

	// Resolución de config: sesión → global → default.
	model := cfg.LLMModel
	reasoning := cfg.LLMReasoning
	agentID := cfg.LLMAgentId
	if s.reportStore != nil {
		sessCfg, err := s.reportStore.LoadSessionConfig(sid)
		if err != nil {
			log.Printf("chat: load session config: %v", err)
		} else if sessCfg != nil {
			if sessCfg.Model != "" {
				model = sessCfg.Model
			}
			if sessCfg.Reasoning != "" {
				reasoning = sessCfg.Reasoning
			}
			if sessCfg.AgentID != "" {
				agentID = sessCfg.AgentID
			}
		}
	}
	if model == "" {
		model = defaultModel
	}
	if agentID == "" {
		agentID = agent.DefaultAgentID
	}
	systemPrompt := agent.DefaultAgentPrompt(agentID)
	if override := cfg.AgentOverrides[agentID]; override != "" {
		systemPrompt = override
	}

	llmMessages, storageMessages := buildChatMessages(cfg, chatReq.Messages)

	s.agentMu.Lock()
	if _, exists := s.activeAgents[sid]; exists {
		s.agentMu.Unlock()
		http.Error(w, "agent already running", http.StatusConflict)
		return
	}
	sa := &SessionAgent{
		SessionID:   sid,
		Messages:    storageMessages,
		Done:        make(chan struct{}),
		Subscribers: make(map[chan agent.Event]struct{}),
	}
	ctx, cancel := context.WithCancel(context.Background())
	sa.Cancel = cancel
	s.activeAgents[sid] = sa
	s.agentMu.Unlock()

	llmClient := llm.NewDeepSeekClient(cfg.LLMApiKey)

	subagentMap := make(map[string]*agent.AgentConfig)
	sc := cfg.SubagentConfig
	if sc == nil {
		sc = make(map[string]storage.SubagentConfig)
	}
	webCfg := sc["web_researcher"]
	webModel := webCfg.Model
	if webModel == "" {
		webModel = defaultModel
	}
	webMaxSteps := webCfg.MaxSteps
	if webMaxSteps <= 0 {
		webMaxSteps = defaultResearcherMaxSteps
	}
	tfClient := tinyfish.NewClient(cfg.TinyfishApiKey)
	researcherCfg := subagents.ResearcherConfig(webModel, webCfg.Reasoning, webMaxSteps, tfClient)
	subagentMap["web_researcher"] = &researcherCfg

	go func() {
		// El servidor es la fuente de verdad: guarda historial + mensaje nuevo ya
		// al empezar. Aquí y no en el handler: el POST responde al instante aunque
		// SQLite esté ocupado, y los suscriptores inmediatos leen el snapshot de
		// sa.Messages en memoria, no de la DB.
		s.persistMessages(sid, storageMessages)

		var assistantContent strings.Builder
		var assistantReasoning strings.Builder

		defer func() {
			sa.mu.Lock()
			content := assistantContent.String()
			reasoningText := assistantReasoning.String()
			var assistantRow *storage.MessageRow
			if content != "" || reasoningText != "" || sa.LiveReportID != "" {
				row := storage.MessageRow{
					Role:        "assistant",
					Content:     content,
					Reasoning:   reasoningText,
					ReportID:    sa.LiveReportID,
					ReportTitle: sa.LiveReportTitle,
				}
				sa.Messages = append(sa.Messages, row)
				assistantRow = &row
			}
			sa.LiveContent = ""
			sa.LiveReasoning = ""
			sa.LiveReportID = ""
			sa.LiveReportTitle = ""
			sa.ToolStatus = ""
			sa.mu.Unlock()

			// El historial ya se persistió al arrancar el run; solo falta añadir
			// la respuesta (también el parcial, si el run se canceló a mitad).
			if assistantRow != nil && s.reportStore != nil {
				if err := s.reportStore.AppendMessage(sid, *assistantRow); err != nil {
					log.Printf("chat: append message (session %s): %v", sid, err)
				}
			}

			s.agentMu.Lock()
			delete(s.activeAgents, sid)
			s.agentMu.Unlock()

			close(sa.Done)
		}()

		// Actualización de estado y fan-out van juntos en sa.Publish para que
		// los snapshots de suscripción no dupliquen ni pierdan eventos. Los
		// closures update corren bajo sa.mu: no deben tomar locks. Los builders
		// solo los escribe esta goroutine (el run es secuencial).
		processEvent := func(ev agent.Event) {
			var update func()
			switch ev.Type {
			case "token":
				if tok, ok := ev.Data.(string); ok {
					update = func() {
						assistantContent.WriteString(tok)
						sa.LiveContent = assistantContent.String()
					}
				}
			case "reasoning":
				if tok, ok := ev.Data.(string); ok {
					update = func() {
						assistantReasoning.WriteString(tok)
						sa.LiveReasoning = assistantReasoning.String()
					}
				}
			case "tool_progress":
				if data, ok := ev.Data.(map[string]interface{}); ok {
					if msg, ok := data["message"].(string); ok {
						update = func() { sa.ToolStatus = msg }
					}
				}
			case "subagent_end":
				update = func() {
					sa.ToolStatus = ""
					if data, ok := ev.Data.(map[string]interface{}); ok {
						if rid, ok := data["reportId"].(string); ok {
							sa.LiveReportID = rid
						}
						if rt, ok := data["title"].(string); ok {
							sa.LiveReportTitle = rt
						}
					}
				}
			}
			sa.Publish(ev, update)
		}

		if s.RagManager != nil {
			docCfg := sc["documentalista"]
			docModel := docCfg.Model
			if docModel == "" {
				docModel = defaultModel
			}
			docMaxSteps := docCfg.MaxSteps
			if docMaxSteps <= 0 {
				docMaxSteps = defaultResearcherMaxSteps
			}
			documentalistaCfg := subagents.DocumentalistaConfig(
				docModel, docCfg.Reasoning, docMaxSteps,
				llmClient,
				s.RagManager.Client(),
				tfClient,
				s.reportStore,
				sc,
				func() string { return sid },
				processEvent,
			)
			subagentMap["documentalista"] = documentalistaCfg
		}

		registry := tools.NewRegistry()
		registry.Register(&agenttools.DeploySubagent{
			LLMClient:   llmClient,
			ReportStore: s.reportStore,
			Subagents:   subagentMap,
			SessionID:   func() string { return sid },
			Emit:        processEvent,
		})

		ag := agent.New(agent.AgentConfig{
			Name:         "orchestrator",
			Model:        model,
			Reasoning:    reasoning,
			MaxSteps:     orchestratorMaxSteps,
			SystemPrompt: systemPrompt,
			Tools:        registry,
			Subagents:    subagentMap,
		}, llmClient)

		if _, err := ag.Run(ctx, llmMessages, processEvent); err != nil {
			log.Printf("chat: agent run (session %s): %v", sid, err)
			// La cancelación del usuario no es un error de cara al chat.
			if ctx.Err() == nil {
				sa.Publish(agent.Event{Type: "error", Data: err.Error()}, nil)
			}
		}
	}()

	w.WriteHeader(http.StatusAccepted)
}

// buildChatMessages separa lo que ve el LLM de lo que se persiste: el historial se
// guarda tal cual llegó y solo el último mensaje del usuario lleva sello de fecha,
// para no invalidar el prefix-cache de DeepSeek en cada turno.
func buildChatMessages(cfg *storage.Config, incoming []chatIncomingMessage) ([]llm.Message, []storage.MessageRow) {
	llmMessages := make([]llm.Message, 0, len(incoming)+2)

	if cfg.UserName != "" || cfg.UserLocation != "" {
		ctxParts := "## Context\n"
		if cfg.UserName != "" {
			ctxParts += fmt.Sprintf("User: %s\n", cfg.UserName)
		}
		if cfg.UserLocation != "" {
			ctxParts += fmt.Sprintf("Location: %s\n", cfg.UserLocation)
		}
		llmMessages = append(llmMessages, llm.Message{Role: llm.RoleSystem, Content: ctxParts})
	}

	formattingRules := "## Formatting rules\n" +
		"- Never use emojis (like ✅, ❌, 🚀, 💡, ⚠️, 🔥) in your responses\n" +
		"- For bulleted lists: use • or standard Markdown -\n" +
		"- For emphasis: use **bold** or *italic*\n" +
		"- For positive/negative indicators: use ✓ and ✗ (Unicode U+2713/U+2717)\n" +
		"- For code: use ``` fenced blocks\n" +
		"- For tips/notes: use > blockquotes with a bold label\n" +
		"- Use plain text and standard Markdown only"
	llmMessages = append(llmMessages, llm.Message{Role: llm.RoleSystem, Content: formattingRules})

	lastUserIdx := -1
	for i, m := range incoming {
		if m.Role == "user" {
			lastUserIdx = i
		}
	}

	now := time.Now()
	dateStr := fmt.Sprintf("%s, %d de %s de %d, %s",
		spanishWeekday(now.Weekday()), now.Day(), spanishMonth(now.Month()), now.Year(),
		now.Format("15:04 MST"))

	storageMessages := make([]storage.MessageRow, 0, len(incoming))
	for i, m := range incoming {
		if m.Role != "user" && m.Role != "assistant" {
			continue
		}
		content := m.Content
		if i == lastUserIdx {
			content = fmt.Sprintf("[%s]\n%s", dateStr, strings.TrimSpace(content))
		}
		llmMessages = append(llmMessages, llm.Message{Role: llm.Role(m.Role), Content: content})
		storageMessages = append(storageMessages, storage.MessageRow{
			Role:        m.Role,
			Content:     m.Content,
			Reasoning:   m.Reasoning,
			ReportID:    m.ReportID,
			ReportTitle: m.ReportTitle,
		})
	}

	return llmMessages, storageMessages
}

func (s *Server) persistMessages(sid string, rows []storage.MessageRow) {
	if s.reportStore == nil {
		return
	}
	if err := s.reportStore.SaveMessages(sid, rows); err != nil {
		log.Printf("chat: save messages (session %s): %v", sid, err)
	}
}

func (s *Server) handleCancelAgent(w http.ResponseWriter, r *http.Request) {
	sid := r.PathValue("id")
	s.agentMu.Lock()
	sa, exists := s.activeAgents[sid]
	s.agentMu.Unlock()
	// La limpieza de activeAgents la hace siempre el defer de la goroutine del run;
	// borrar aquí permitiría arrancar un segundo run concurrente para la misma sesión.
	if exists {
		sa.Cancel()
	}
	w.WriteHeader(http.StatusNoContent)
}

func spanishMonth(m time.Month) string {
	months := []string{
		"enero", "febrero", "marzo", "abril", "mayo", "junio",
		"julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
	}
	if m >= 1 && m <= 12 {
		return months[m-1]
	}
	return m.String()
}

func spanishWeekday(d time.Weekday) string {
	days := []string{"domingo", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado"}
	if d >= 0 && d <= 6 {
		return days[d]
	}
	return d.String()
}
