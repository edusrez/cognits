package server

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/eduardosrez/learnit/internal/storage"
)

func (s *Server) handleCreateSession(w http.ResponseWriter, r *http.Request) {
	if !s.ensureSessions(w) {
		return
	}

	now := time.Now()
	id := now.Format("2006-01-02T15-04")
	session := storage.Session{
		ID:        id,
		Name:      id,
		CreatedAt: now.Format(time.RFC3339),
	}

	if err := s.store.SaveSession(session); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(session)
}

func (s *Server) handleListSessions(w http.ResponseWriter, r *http.Request) {
	if !s.ensureSessions(w) {
		return
	}

	sessions, err := s.store.ListSessions()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sessions)
}

func (s *Server) handleRenameSession(w http.ResponseWriter, r *http.Request) {
	if !s.ensureSessions(w) {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		http.Error(w, "missing id", http.StatusBadRequest)
		return
	}

	var body struct {
		Name string `json:"name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}
	if len(body.Name) > 120 {
		http.Error(w, "name too long", http.StatusBadRequest)
		return
	}

	if err := s.store.RenameSession(id, body.Name); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleDeleteSession(w http.ResponseWriter, r *http.Request) {
	if !s.ensureSessions(w) {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		http.Error(w, "missing id", http.StatusBadRequest)
		return
	}

	if err := s.store.DeleteSession(id); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Los informes se conservan: son biblioteca transversal en la vista Learn It.
	if s.reportStore != nil {
		if err := s.reportStore.DeleteMessagesBySession(id); err != nil {
			log.Printf("sessions: delete messages (session %s): %v", id, err)
		}
		if err := s.reportStore.DeleteSessionConfig(id); err != nil {
			log.Printf("sessions: delete session config (session %s): %v", id, err)
		}
	}

	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) ensureSessions(w http.ResponseWriter) bool {
	if s.store == nil {
		http.Error(w, "almacenamiento no disponible", http.StatusServiceUnavailable)
		return false
	}
	return true
}
