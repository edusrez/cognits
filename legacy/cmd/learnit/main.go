package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/eduardosrez/learnit/internal/rag"
	"github.com/eduardosrez/learnit/internal/server"
)

var buildTime = "unknown"

func main() {
	srv := server.New()

	if err := srv.Start(); err != nil {
		log.Fatalf("server: %v", err)
	}

	cwd, _ := os.Getwd()

	if err := rag.EnsureDependencies(cwd); err != nil {
		log.Printf("rag: deps: %v (RAG features disabled)", err)
	} else {
		ragMgr, err := rag.StartManager(context.Background(), 7825, cwd)
		if err != nil {
			log.Printf("rag: %v (RAG features disabled)", err)
		} else {
			srv.RagManager = ragMgr
			defer ragMgr.Shutdown()
		}
	}

	fmt.Printf("Learn It -> %s\n", srv.URL())
	fmt.Printf("Built: %s\n", strings.ReplaceAll(buildTime, "_", " "))
	srv.OpenBrowser()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	// Un segundo Ctrl+C durante el drenaje mata el proceso en seco.
	signal.Reset(syscall.SIGINT, syscall.SIGTERM)
	srv.Shutdown(5 * time.Second)
	fmt.Println("\nbye")
}
