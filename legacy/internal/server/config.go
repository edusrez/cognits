package server

import (
	"encoding/json"
	"net/http"

	"github.com/eduardosrez/learnit/internal/storage"
)

type configResponse struct {
	LLMProvider  string                     `json:"llmProvider"`
	LLMAgentId   string                     `json:"llmAgentId"`
	LLMApiKey   string                      `json:"llmApiKey"`
	LLMModel    string                      `json:"llmModel"`
	LLMReasoning string                     `json:"llmReasoning"`
	AgentOverrides   map[string]string           `json:"agentOverrides"`
	ChatFontSize     int                         `json:"chatFontSize"`
	TinyfishApiKey   string                      `json:"tinyfishApiKey"`
	TinyfishTier     string                      `json:"tinyfishTier"`
	SubagentConfig   map[string]storage.SubagentConfig `json:"subagentConfig"`
	UserName             string                     `json:"userName"`
	UserLocation         string                     `json:"userLocation"`
	DefaultLearnitViewport string                  `json:"defaultLearnitViewport"`
	WriteLangs           []string                   `json:"writeLangs"`
}

// Las claves nunca salen en claro por la API: GET devuelve "••••" + últimos 4
// y PUT conserva la clave guardada si recibe de vuelta ese valor enmascarado.
func maskKey(key string) string {
	if key == "" {
		return ""
	}
	if len(key) <= 4 {
		return "••••"
	}
	return "••••" + key[len(key)-4:]
}

func (s *Server) handleGetConfig(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(configResponse{})
		return
	}

	cfg, err := s.store.LoadConfig()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	resp := configResponse{
		LLMProvider:  cfg.LLMProvider,
		LLMAgentId:   cfg.LLMAgentId,
		LLMApiKey:    maskKey(cfg.LLMApiKey),
		LLMModel:     cfg.LLMModel,
		LLMReasoning: cfg.LLMReasoning,
		AgentOverrides:    cfg.AgentOverrides,
		ChatFontSize:      cfg.ChatFontSize,
		TinyfishApiKey:    maskKey(cfg.TinyfishApiKey),
		TinyfishTier:      cfg.TinyfishTier,
		SubagentConfig:    cfg.SubagentConfig,
		UserName:          cfg.UserName,
		UserLocation:      cfg.UserLocation,
		DefaultLearnitViewport: cfg.DefaultLearnitViewport,
		WriteLangs:        cfg.WriteLangs,
	}
	if resp.SubagentConfig == nil {
		resp.SubagentConfig = make(map[string]storage.SubagentConfig)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (s *Server) handlePutConfig(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "store not initialized", http.StatusInternalServerError)
		return
	}

	var cfg configResponse
	if err := json.NewDecoder(r.Body).Decode(&cfg); err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}

	if cfg.LLMProvider != "" && cfg.LLMProvider != "deepseek" {
		http.Error(w, "invalid provider", http.StatusBadRequest)
		return
	}
	if cfg.LLMModel != "" && cfg.LLMModel != "deepseek-v4-pro" && cfg.LLMModel != "deepseek-v4-flash" {
		http.Error(w, "invalid model", http.StatusBadRequest)
		return
	}
	if cfg.LLMReasoning != "" &&
		cfg.LLMReasoning != "disabled" &&
		cfg.LLMReasoning != "high" &&
		cfg.LLMReasoning != "max" {
		http.Error(w, "invalid reasoning value", http.StatusBadRequest)
		return
	}

	if current := s.configSnapshot(); current != nil {
		if cfg.LLMApiKey == maskKey(current.LLMApiKey) {
			cfg.LLMApiKey = current.LLMApiKey
		}
		if cfg.TinyfishApiKey == maskKey(current.TinyfishApiKey) {
			cfg.TinyfishApiKey = current.TinyfishApiKey
		}
	}

	newCfg := storage.Config{
		LLMProvider:  cfg.LLMProvider,
		LLMAgentId:   cfg.LLMAgentId,
		LLMApiKey:    cfg.LLMApiKey,
		LLMModel:     cfg.LLMModel,
		LLMReasoning: cfg.LLMReasoning,
		AgentOverrides:    cfg.AgentOverrides,
		ChatFontSize:      cfg.ChatFontSize,
		TinyfishApiKey:    cfg.TinyfishApiKey,
		TinyfishTier:      cfg.TinyfishTier,
		SubagentConfig:    cfg.SubagentConfig,
		UserName:          cfg.UserName,
		UserLocation:      cfg.UserLocation,
		DefaultLearnitViewport: cfg.DefaultLearnitViewport,
		WriteLangs:        cfg.WriteLangs,
	}

	if err := s.store.SaveConfig(newCfg); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	s.setConfig(&newCfg)

	w.WriteHeader(http.StatusNoContent)
}
