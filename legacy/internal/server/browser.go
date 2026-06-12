package server

import (
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

func (s *Server) OpenBrowser() {
	url := s.URL() + "?v=" + strconv.FormatInt(time.Now().Unix(), 10)

	if isWSL() {
		for _, args := range [][]string{
			{"cmd.exe", "/c", "start", url},
			{"powershell.exe", "-Command", "Start-Process", url},
		} {
			if cmd := exec.Command(args[0], args[1:]...); cmd.Run() == nil {
				return
			}
		}
	}

	switch runtime.GOOS {
	case "linux":
		exec.Command("xdg-open", url).Start()
	case "darwin":
		exec.Command("open", url).Start()
	case "windows":
		exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	}
}

func isWSL() bool {
	data, err := os.ReadFile("/proc/version")
	if err != nil {
		return false
	}
	return strings.Contains(strings.ToLower(string(data)), "microsoft")
}
