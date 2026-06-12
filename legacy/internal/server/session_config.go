package server

import (
	"encoding/json"
	"net/http"

	"github.com/eduardosrez/learnit/internal/storage"
)

func (s *Server) handleGetSessionConfig(w http.ResponseWriter, r *http.Request) {
	if s.reportStore == nil {
		http.Error(w, "db not available", http.StatusInternalServerError)
		return
	}

	sessionID := r.PathValue("id")
	cfg, err := s.reportStore.LoadSessionConfig(sessionID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if cfg == nil {
		cfg = &storage.SessionConfigRow{
			SessionID: sessionID,
			Provider:  "deepseek",
			Model:     "deepseek-v4-pro",
			Reasoning: "max",
			AgentID:   "orquestador",
		}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(cfg)
}

func (s *Server) handlePutSessionConfig(w http.ResponseWriter, r *http.Request) {
	if s.reportStore == nil {
		http.Error(w, "db not available", http.StatusInternalServerError)
		return
	}

	var cfg storage.SessionConfigRow
	if err := json.NewDecoder(r.Body).Decode(&cfg); err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}
	cfg.SessionID = r.PathValue("id")

	if err := s.reportStore.SaveSessionConfig(cfg); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}
