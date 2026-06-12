package server

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/eduardosrez/learnit/internal/storage"
)

func (s *Server) handleGetReport(w http.ResponseWriter, r *http.Request) {
	if s.reportStore == nil {
		http.Error(w, "reports not available", http.StatusInternalServerError)
		return
	}

	id := r.PathValue("id")
	report, err := s.reportStore.Get(id)
	if err != nil {
		http.Error(w, "report not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(report)
}

func (s *Server) handleListReports(w http.ResponseWriter, r *http.Request) {
	if s.reportStore == nil {
		http.Error(w, "reports not available", http.StatusInternalServerError)
		return
	}

	q := r.URL.Query()
	page, _ := strconv.Atoi(q.Get("page"))
	if page < 1 {
		page = 1
	}
	limit, _ := strconv.Atoi(q.Get("limit"))
	sort := q.Get("sort")
	if sort == "" {
		sort = "date_desc"
	}
	search := q.Get("search")

	if search != "" {
		ftsResult, err := s.reportStore.SearchReportsFTS(page, limit, sort, search)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ftsResult)
		return
	}

	result, err := s.reportStore.SearchReports(page, limit, sort, search)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	if result.Reports == nil {
		result.Reports = []storage.Report{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func (s *Server) handleDeleteReport(w http.ResponseWriter, r *http.Request) {
	if s.reportStore == nil {
		http.Error(w, "reports not available", http.StatusInternalServerError)
		return
	}

	id := r.PathValue("id")
	if err := s.reportStore.DeleteReport(id); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}
