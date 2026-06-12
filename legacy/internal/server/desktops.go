package server

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"

	"github.com/eduardosrez/learnit/internal/storage"
)

type desktopState struct {
	Desktops    []json.RawMessage `json:"desktops"`
	ActiveIndex int               `json:"activeIndex"`
}

func (s *Server) desktopPath() string {
	cwd, _ := os.Getwd()
	return filepath.Join(cwd, ".learnit", "desktops.json")
}

func (s *Server) handleGetDesktops(w http.ResponseWriter, r *http.Request) {
	s.desktopMu.Lock()
	data, err := os.ReadFile(s.desktopPath())
	s.desktopMu.Unlock()
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(desktopState{Desktops: []json.RawMessage{}, ActiveIndex: 0})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(data)
}

func (s *Server) handlePutDesktops(w http.ResponseWriter, r *http.Request) {
	var ds desktopState
	if err := json.NewDecoder(r.Body).Decode(&ds); err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}

	if ds.Desktops == nil {
		ds.Desktops = []json.RawMessage{}
	}

	data, err := json.MarshalIndent(ds, "", "  ")
	if err != nil {
		http.Error(w, "marshal error", http.StatusInternalServerError)
		return
	}

	dir := filepath.Dir(s.desktopPath())
	if err := os.MkdirAll(dir, 0755); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	// Dos pestañas pueden persistir a la vez (BroadcastChannel): serializar y
	// escribir atómicamente para no dejar el JSON truncado.
	s.desktopMu.Lock()
	err = storage.WriteFileAtomic(s.desktopPath(), data, 0644)
	s.desktopMu.Unlock()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}
