package rag

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

type Manager struct {
	cmd     *exec.Cmd
	pgid    int
	client  *Client
	baseURL string
}

func resolvePython(projectRoot string) (string, error) {
	for _, exe := range pythonExeCandidates {
		if exec.Command(exe, "-m", "pip", "--version").Run() == nil {
			return exe, nil
		}
	}

	venvDir := filepath.Join(projectRoot, ".learnit", "rag", "venv")
	pythonPath := filepath.Join(venvDir, venvPythonRelPath)
	if _, err := os.Stat(pythonPath); err == nil {
		return pythonPath, nil
	}

	log.Print("rag: creating virtual environment...")
	cmd := exec.Command(pythonExeCandidates[0], "-m", "venv", venvDir)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("cannot create venv; install python3-venv (sudo apt install python3-venv python3-pip)")
	}
	return pythonPath, nil
}

func EnsureDependencies(projectRoot string) error {
	if _, err := exec.LookPath(pythonExeCandidates[0]); err != nil {
		return fmt.Errorf("rag: python not found (%s): %w", pythonExeCandidates[0], err)
	}

	pythonPath, err := resolvePython(projectRoot)
	if err != nil {
		return err
	}

	_, reqPath, err := ExtractTo(projectRoot)
	if err != nil {
		return fmt.Errorf("rag: extract: %w", err)
	}

	log.Print("rag: installing Python dependencies...")
	cmd := exec.Command(pythonPath, "-m", "pip", "install", "--timeout", "30", "-r", reqPath)
	cmd.Dir = projectRoot
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("rag: pip install failed: %w", err)
	}
	log.Print("rag: dependencies ready")
	return nil
}

func (m *Manager) Client() *Client {
	return m.client
}

func (m *Manager) waitHealthy(timeout time.Duration) error {
	deadline := time.After(timeout)
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-deadline:
			return fmt.Errorf("timeout after %v", timeout)
		case <-ticker.C:
			resp, err := http.Get(m.baseURL + "/health")
			if err == nil {
				resp.Body.Close()
				if resp.StatusCode == 200 {
					return nil
				}
			}
		}
	}
}
