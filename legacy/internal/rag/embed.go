package rag

import (
	_ "embed"
	"fmt"
	"os"
	"path/filepath"
)

//go:embed sidecar.py
var sidecarPy []byte

//go:embed requirements.txt
var requirementsTxt []byte

func ExtractTo(projectRoot string) (sidecarPath, reqPath string, err error) {
	ragDir := filepath.Join(projectRoot, ".learnit", "rag")
	if err := os.MkdirAll(ragDir, 0755); err != nil {
		return "", "", fmt.Errorf("rag: mkdir: %w", err)
	}

	sidecarPath = filepath.Join(ragDir, "sidecar.py")
	reqPath = filepath.Join(ragDir, "requirements.txt")

	if err := os.WriteFile(sidecarPath, sidecarPy, 0644); err != nil {
		return "", "", fmt.Errorf("rag: write sidecar: %w", err)
	}
	if err := os.WriteFile(reqPath, requirementsTxt, 0644); err != nil {
		return "", "", fmt.Errorf("rag: write requirements: %w", err)
	}
	return sidecarPath, reqPath, nil
}
