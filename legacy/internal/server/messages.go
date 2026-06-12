package server

import (
	"encoding/json"
	"net/http"

	"github.com/eduardosrez/learnit/internal/storage"
)

func (s *Server) handleGetMessages(w http.ResponseWriter, r *http.Request) {
	if s.reportStore == nil {
		http.Error(w, "db not available", http.StatusInternalServerError)
		return
	}

	sessionID := r.PathValue("id")
	msgs, err := s.reportStore.LoadMessages(sessionID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if msgs == nil {
		msgs = []storage.MessageRow{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(msgs)
}
