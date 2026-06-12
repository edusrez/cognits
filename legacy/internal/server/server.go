package server

import (
	"context"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/eduardosrez/learnit/internal/agent"
	"github.com/eduardosrez/learnit/internal/rag"
	"github.com/eduardosrez/learnit/internal/storage"
)

const defaultPort = "5173"

type SessionAgent struct {
	SessionID string
	Cancel    context.CancelFunc
	// Done se cierra cuando el run del agente termina; señala fin a los suscriptores.
	Done chan struct{}

	mu              sync.RWMutex
	Messages        []storage.MessageRow
	ToolStatus      string
	LiveContent     string
	LiveReasoning   string
	LiveReportID    string
	LiveReportTitle string
	Subscribers     map[chan agent.Event]struct{}
}

// Publish actualiza el estado del agente y hace el fan-out en la MISMA
// sección crítica: así un evento o bien precede a un snapshot (está en él y
// no en el canal) o bien lo sigue (está en el canal y no en él) — nunca en
// ambos, que era la carrera que duplicaba tokens al suscribirse a mitad de
// stream. update no debe tomar sa.mu ni llamar a Publish.
func (sa *SessionAgent) Publish(event agent.Event, update func()) {
	sa.mu.Lock()
	defer sa.mu.Unlock()
	if update != nil {
		update()
	}
	// El envío dropea eventos si el buffer está lleno (no puede bloquear al
	// agente); un buffer amplio hace los drops improbables y la recarga de
	// DB en "done" sigue siendo la red de seguridad.
	for ch := range sa.Subscribers {
		select {
		case ch <- event:
		default:
		}
	}
}

// AgentSnapshot es la copia atómica del estado vivo que se entrega junto a la
// suscripción para construir el evento history sin carreras.
type AgentSnapshot struct {
	Messages        []storage.MessageRow
	ToolStatus      string
	LiveContent     string
	LiveReasoning   string
	LiveReportID    string
	LiveReportTitle string
}

// SubscribeWithSnapshot registra el canal y copia el estado bajo el mismo
// lock que usa Publish: todo evento posterior llega por el canal y ninguno
// anterior se reenvía duplicado.
func (sa *SessionAgent) SubscribeWithSnapshot() (chan agent.Event, AgentSnapshot) {
	ch := make(chan agent.Event, 1024)
	sa.mu.Lock()
	defer sa.mu.Unlock()
	sa.Subscribers[ch] = struct{}{}
	msgs := make([]storage.MessageRow, len(sa.Messages))
	copy(msgs, sa.Messages)
	return ch, AgentSnapshot{
		Messages:        msgs,
		ToolStatus:      sa.ToolStatus,
		LiveContent:     sa.LiveContent,
		LiveReasoning:   sa.LiveReasoning,
		LiveReportID:    sa.LiveReportID,
		LiveReportTitle: sa.LiveReportTitle,
	}
}

func (sa *SessionAgent) Unsubscribe(ch chan agent.Event) {
	sa.mu.Lock()
	delete(sa.Subscribers, ch)
	sa.mu.Unlock()
}

type Server struct {
	Port    int
	Mux     *http.ServeMux
	ln      net.Listener
	httpSrv *http.Server
	html    []byte

	store       *storage.Store
	reportStore *storage.ReportStore

	cfgMu        sync.RWMutex
	cachedConfig *storage.Config

	activeAgents map[string]*SessionAgent
	agentMu      sync.Mutex

	desktopMu sync.Mutex

	RagManager *rag.Manager
}

func New() *Server {
	mux := http.NewServeMux()
	s := &Server{Mux: mux, activeAgents: make(map[string]*SessionAgent)}

	cwd, err := os.Getwd()
	if err == nil {
		learnitDir := filepath.Join(cwd, ".learnit")
		store, err := storage.NewStore(learnitDir)
		if err != nil {
			log.Printf("storage: init store: %v", err)
		} else {
			s.store = store
			if err := s.store.InitSessionsDir(); err != nil {
				log.Printf("storage: init sessions dir: %v", err)
			}
			cfg, err := s.store.LoadConfig()
			if err != nil {
				log.Printf("storage: load config: %v", err)
				cfg = &storage.Config{}
			}
			s.cachedConfig = cfg

			dbPath := filepath.Join(learnitDir, "learnit.db")
			rs, err := storage.NewReportStore(dbPath)
			if err != nil {
				log.Printf("storage: init db: %v", err)
			} else {
				s.reportStore = rs
			}
		}
	}

	if os.Getenv("ENV") == "dev" {
		s.registerDevProxy(mux)
	} else {
		s.registerProdFrontend(mux)
	}

	mux.HandleFunc("GET /api/tree", s.handleTree)
	mux.HandleFunc("GET /api/health", s.handleHealth)
	mux.HandleFunc("GET /api/agents", s.handleGetAgents)
	mux.HandleFunc("POST /api/sessions", s.handleCreateSession)
	mux.HandleFunc("GET /api/sessions", s.handleListSessions)
	mux.HandleFunc("PUT /api/sessions/{id}", s.handleRenameSession)
	mux.HandleFunc("DELETE /api/sessions/{id}", s.handleDeleteSession)
	mux.HandleFunc("GET /api/config", s.handleGetConfig)
	mux.HandleFunc("PUT /api/config", s.handlePutConfig)
	mux.HandleFunc("POST /api/chat", s.handleChat)
	mux.HandleFunc("GET /api/reports/{id}", s.handleGetReport)
	mux.HandleFunc("DELETE /api/reports/{id}", s.handleDeleteReport)
	mux.HandleFunc("GET /api/reports", s.handleListReports)
	mux.HandleFunc("GET /api/sessions/{id}/messages", s.handleGetMessages)
	mux.HandleFunc("GET /api/sessions/{id}/config", s.handleGetSessionConfig)
	mux.HandleFunc("PUT /api/sessions/{id}/config", s.handlePutSessionConfig)
	mux.HandleFunc("GET /api/sessions/{id}/stream", s.handleSessionStream)
	mux.HandleFunc("DELETE /api/sessions/{id}/agent", s.handleCancelAgent)
	mux.HandleFunc("GET /api/desktops", s.handleGetDesktops)
	mux.HandleFunc("PUT /api/desktops", s.handlePutDesktops)

	return s
}

func (s *Server) configSnapshot() *storage.Config {
	s.cfgMu.RLock()
	defer s.cfgMu.RUnlock()
	return s.cachedConfig
}

func (s *Server) setConfig(cfg *storage.Config) {
	s.cfgMu.Lock()
	s.cachedConfig = cfg
	s.cfgMu.Unlock()
}

func (s *Server) Start() error {
	s.maybeRebuild()

	host := os.Getenv("LEARNIT_HOST")
	if host == "" {
		host = "127.0.0.1"
	}
	port := defaultPort
	if p := os.Getenv("PORT"); p != "" {
		port = p
	}

	var err error
	s.ln, err = net.Listen("tcp", net.JoinHostPort(host, port))
	if err != nil {
		return err
	}
	s.Port = s.ln.Addr().(*net.TCPAddr).Port

	// Sin ReadTimeout/WriteTimeout: cortarían los SSE de larga duración. El
	// keepalive de session_stream ya detecta clientes muertos al escribir.
	srv := &http.Server{
		Handler:           s.Mux,
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       120 * time.Second,
	}
	s.httpSrv = srv
	go func() {
		if err := srv.Serve(s.ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("server: %v", err)
		}
	}()

	return nil
}

// DrainAgents cancela todos los runs activos y espera a que sus defers
// persistan la respuesta parcial, con un timeout total compartido.
func (s *Server) DrainAgents(timeout time.Duration) {
	s.agentMu.Lock()
	agents := make([]*SessionAgent, 0, len(s.activeAgents))
	for _, sa := range s.activeAgents {
		agents = append(agents, sa)
	}
	s.agentMu.Unlock()

	for _, sa := range agents {
		sa.Cancel()
	}

	timer := time.NewTimer(timeout)
	defer timer.Stop()
	for _, sa := range agents {
		select {
		case <-sa.Done:
		case <-timer.C:
			log.Printf("server: drain timeout (session %s)", sa.SessionID)
			return
		}
	}
}

// Shutdown cierra el listener (ningún run nuevo puede arrancar), drena los
// agentes activos y espera el cierre HTTP. El http.Shutdown corre en paralelo:
// espera a los handlers SSE en vuelo, que solo terminan cuando el drenaje
// cierra sus canales Done — bloquear antes del drain sería un interbloqueo.
func (s *Server) Shutdown(timeout time.Duration) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	httpDone := make(chan struct{})
	if s.httpSrv != nil {
		go func() {
			if err := s.httpSrv.Shutdown(ctx); err != nil {
				log.Printf("server: shutdown: %v", err)
			}
			close(httpDone)
		}()
	} else {
		close(httpDone)
	}

	s.DrainAgents(timeout)
	<-httpDone
}

func (s *Server) URL() string {
	return "http://localhost:" + strconv.Itoa(s.Port)
}
