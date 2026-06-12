package server

import (
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

var watchPaths = []string{
	"frontend/src",
	"frontend/index.html",
	"frontend/vite.config.ts",
	"frontend/package.json",
	"cmd",
	"internal",
}

func (s *Server) maybeRebuild() {
	cwd, err := os.Getwd()
	if err != nil {
		return
	}
	if !isSourceFolder(cwd) {
		return
	}

	distFile := filepath.Join(cwd, "internal", "server", "dist", "index.html")
	distInfo, err := os.Stat(distFile)
	if err != nil || anyNewer(cwd, watchPaths, distInfo.ModTime()) {
		s.runRebuild()
	}
}

func isSourceFolder(cwd string) bool {
	for _, marker := range []string{"go.mod", "frontend/package.json"} {
		if _, err := os.Stat(filepath.Join(cwd, marker)); err != nil {
			return false
		}
	}
	return true
}

func anyNewer(cwd string, paths []string, t time.Time) bool {
	for _, p := range paths {
		full := filepath.Join(cwd, p)
		if newerThan(full, t) {
			return true
		}
	}
	return false
}

func newerThan(path string, t time.Time) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	if !info.IsDir() {
		return info.ModTime().After(t)
	}
	newer := false
	filepath.Walk(path, func(_ string, fi os.FileInfo, err error) error {
		if err != nil || fi.IsDir() {
			return nil
		}
		if fi.ModTime().After(t) {
			newer = true
			return filepath.SkipDir
		}
		return nil
	})
	return newer
}

func (s *Server) runRebuild() {
	log.Println("→ source updated, rebuilding...")
	cwd, _ := os.Getwd()
	cmd := exec.Command("./build.sh")
	cmd.Dir = cwd
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Printf("rebuild: ./build.sh failed: %v", err)
		return
	}
	log.Println("→ starting updated binary...")

	exe, err := os.Executable()
	if err != nil {
		log.Printf("rebuild: os.Executable: %v", err)
		return
	}

	newBin := filepath.Join(cwd, "learnit")
	if newBin != exe {
		data, err := os.ReadFile(newBin)
		if err != nil {
			log.Printf("rebuild: read new binary: %v", err)
			return
		}
		tmp, err := os.CreateTemp(filepath.Dir(exe), "learnit-tmp-*")
		if err != nil {
			log.Printf("rebuild: create temp: %v", err)
			return
		}
		if _, err := tmp.Write(data); err != nil {
			tmp.Close()
			log.Printf("rebuild: write temp: %v", err)
			return
		}
		if err := tmp.Chmod(0755); err != nil {
			tmp.Close()
			log.Printf("rebuild: chmod temp: %v", err)
			return
		}
		tmp.Close()
		if err := os.Rename(tmp.Name(), exe); err != nil {
			log.Printf("rebuild: rename: %v", err)
			return
		}
	}

	if err := syscall.Exec(exe, os.Args, os.Environ()); err != nil {
		log.Printf("rebuild: syscall.Exec: %v", err)
	}
}
