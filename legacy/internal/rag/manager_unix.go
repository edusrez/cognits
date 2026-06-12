//go:build !windows

package rag

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

var pythonExeCandidates = []string{"python3", "python"}
var venvPythonRelPath = filepath.Join("bin", "python")

func StartManager(ctx context.Context, port int, projectRoot string) (*Manager, error) {
	sidecarPath, _, err := ExtractTo(projectRoot)
	if err != nil {
		return nil, fmt.Errorf("rag: extract: %w", err)
	}

	pythonPath, err := resolvePython(projectRoot)
	if err != nil {
		return nil, err
	}

	baseURL := fmt.Sprintf("http://127.0.0.1:%d", port)

	cmd := exec.Command(pythonPath, "-u", sidecarPath)
	cmd.Dir = projectRoot
	cmd.Env = append(os.Environ(),
		"RAG_PORT="+fmt.Sprint(port),
		"LEARNIT_RAG_PATH="+filepath.Join(projectRoot, ".learnit", "rag", "chroma_db"),
		"PYTHONUNBUFFERED=1",
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("rag: start sidecar: %w", err)
	}

	m := &Manager{
		cmd:     cmd,
		pgid:    cmd.Process.Pid,
		client:  NewClient(baseURL),
		baseURL: baseURL,
	}

	if err := m.waitHealthy(60 * time.Second); err != nil {
		m.Shutdown()
		return nil, fmt.Errorf("rag: sidecar not healthy: %w", err)
	}

	log.Printf("rag: sidecar healthy on %s", baseURL)
	return m, nil
}

func (m *Manager) Shutdown() {
	if m.cmd == nil || m.cmd.Process == nil {
		return
	}

	log.Print("rag: shutting down sidecar...")

	if err := m.cmd.Process.Signal(syscall.SIGTERM); err == nil {
		done := make(chan struct{})
		go func() {
			m.cmd.Wait()
			close(done)
		}()
		select {
		case <-done:
		case <-time.After(10 * time.Second):
			log.Print("rag: sidecar didn't exit, force killing...")
			syscall.Kill(-m.pgid, syscall.SIGKILL)
		}
	} else {
		m.cmd.Process.Kill()
	}

	log.Print("rag: sidecar stopped")
}
