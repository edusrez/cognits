package server

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type FileNode struct {
	Name     string     `json:"name"`
	Path     string     `json:"path"`
	IsDir    bool       `json:"isDir"`
	Children []FileNode `json:"children,omitempty"`
}

const (
	treeMaxDepth   = 6
	treeMaxEntries = 2000
)

var treeSkipDirs = map[string]bool{
	"node_modules": true,
	"dist":         true,
	"vendor":       true,
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func (s *Server) handleTree(w http.ResponseWriter, r *http.Request) {
	dir, err := os.Getwd()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	budget := treeMaxEntries
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(buildTree(dir, treeMaxDepth, &budget))
}

func buildTree(dir string, maxDepth int, budget *int) FileNode {
	node := FileNode{Name: filepath.Base(dir), Path: dir, IsDir: true}
	if maxDepth <= 0 || *budget <= 0 {
		return node
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		return node
	}

	sort.Slice(entries, func(i, j int) bool {
		if entries[i].IsDir() != entries[j].IsDir() {
			return entries[i].IsDir()
		}
		return strings.ToLower(entries[i].Name()) < strings.ToLower(entries[j].Name())
	})

	for _, e := range entries {
		if *budget <= 0 {
			break
		}
		name := e.Name()
		if name == "" || name[0] == '.' || treeSkipDirs[name] {
			continue
		}
		if e.Type()&os.ModeSymlink != 0 {
			continue
		}
		*budget--
		child := FileNode{
			Name:  name,
			Path:  filepath.Join(dir, name),
			IsDir: e.IsDir(),
		}
		if e.IsDir() {
			child.Children = buildTree(child.Path, maxDepth-1, budget).Children
		}
		node.Children = append(node.Children, child)
	}
	return node
}
