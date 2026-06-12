package server

import (
	"embed"
	"io/fs"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"regexp"
	"strconv"
	"time"
)

//go:embed all:dist
var frontendAssets embed.FS

var assetRef = regexp.MustCompile(`="(/assets/[^"?]+)"`)

const devVitePort = "5174"

func (s *Server) registerDevProxy(mux *http.ServeMux) {
	target, _ := url.Parse("http://localhost:" + devVitePort)
	proxy := httputil.NewSingleHostReverseProxy(target)
	mux.Handle("GET /", proxy)
	log.Println("[frontend] dev mode: proxying to Vite at http://localhost:" + devVitePort)
}

func (s *Server) registerProdFrontend(mux *http.ServeMux) {
	subFS, _ := fs.Sub(frontendAssets, "dist")
	fileServer := http.FileServer(http.FS(subFS))
	s.html = s.loadIndexHTML()

	// Solo el index va sin caché; los assets llevan hash/cache-buster en el
	// nombre y pueden cachearse con normalidad.
	mux.Handle("GET /", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" && s.html != nil {
			w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.Write(s.html)
			return
		}
		fileServer.ServeHTTP(w, r)
	}))
}

func (s *Server) loadIndexHTML() []byte {
	data, err := frontendAssets.ReadFile("dist/index.html")
	if err != nil {
		log.Printf("frontend: failed to read index.html: %v", err)
		return nil
	}
	v := strconv.FormatInt(time.Now().UnixNano(), 36)
	return assetRef.ReplaceAll(data, []byte(`="$1?v=`+v+`"`))
}
