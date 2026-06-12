package server

import (
	"encoding/json"
	"net/http"

	"github.com/eduardosrez/learnit/internal/agent"
)

func (s *Server) handleGetAgents(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(agent.DefaultAgents)
}
