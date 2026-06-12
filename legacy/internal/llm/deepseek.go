package llm

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

// Si la API deja de enviar datos este tiempo, el stream se da por muerto.
// Cubre conexiones que se quedan mudas sin FIN (NAT, wifi caída).
const streamIdleTimeout = 120 * time.Second

type DeepSeekClient struct {
	apiKey     string
	baseURL    string
	httpClient *http.Client
}

func NewDeepSeekClient(apiKey string) *DeepSeekClient {
	return &DeepSeekClient{
		apiKey:  apiKey,
		baseURL: "https://api.deepseek.com/chat/completions",
		// Timeouts por fase y nunca Client.Timeout: un timeout global
		// cortaría streams legítimos de varios minutos.
		httpClient: &http.Client{
			Transport: &http.Transport{
				DialContext:           (&net.Dialer{Timeout: 10 * time.Second}).DialContext,
				TLSHandshakeTimeout:   10 * time.Second,
				ResponseHeaderTimeout: 60 * time.Second,
				ForceAttemptHTTP2:     true,
			},
		},
	}
}

type deepseekReq struct {
	Model    string         `json:"model"`
	Messages []Message      `json:"messages"`
	Tools    []ToolDef      `json:"tools,omitempty"`
	Stream   bool           `json:"stream"`
	Thinking *deepseekThink `json:"thinking,omitempty"`
}

type deepseekThink struct {
	Type string `json:"type"`
}

func (c *DeepSeekClient) ChatCompletionStream(
	ctx context.Context,
	messages []Message,
	tools []ToolDef,
	model string,
	reasoning string,
	onChunk func(chunk StreamChunk),
) error {
	// La API de thinking es binaria: "high"/"max" → enabled. Con tools se omite
	// el parámetro (la API lo rechaza en esa combinación; pendiente de verificar
	// si versiones futuras lo aceptan).
	var think *deepseekThink
	if len(tools) == 0 {
		t := "enabled"
		if reasoning == "disabled" {
			t = "disabled"
		}
		think = &deepseekThink{Type: t}
	}

	body, err := json.Marshal(deepseekReq{
		Model:    model,
		Messages: messages,
		Tools:    tools,
		Stream:   true,
		Thinking: think,
	})
	if err != nil {
		return fmt.Errorf("deepseek: marshal request: %w", err)
	}

	// Contexto derivado para el watchdog de inactividad: se rearma con cada
	// línea recibida y cancela el stream si la API se queda muda.
	streamCtx, cancelStream := context.WithCancel(ctx)
	defer cancelStream()

	req, err := http.NewRequestWithContext(streamCtx, "POST", c.baseURL, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("deepseek: create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	watchdog := time.AfterFunc(streamIdleTimeout, cancelStream)
	defer watchdog.Stop()

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("deepseek: request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		// Limitar la lectura (un cuerpo enorme inflaría logs/chat) y extraer el
		// mensaje del JSON de error de la API si lo trae.
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<10))
		msg := strings.TrimSpace(string(raw))
		var apiErr struct {
			Error struct {
				Message string `json:"message"`
			} `json:"error"`
		}
		if json.Unmarshal(raw, &apiErr) == nil && apiErr.Error.Message != "" {
			msg = apiErr.Error.Message
		}
		return fmt.Errorf("deepseek: HTTP %d: %s", resp.StatusCode, msg)
	}

	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	for scanner.Scan() {
		watchdog.Reset(streamIdleTimeout)

		select {
		case <-streamCtx.Done():
			return streamCtx.Err()
		default:
		}

		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := strings.TrimPrefix(line, "data: ")
		if data == "[DONE]" {
			return nil
		}

		var chunk StreamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue
		}
		onChunk(chunk)
	}
	if err := scanner.Err(); err != nil {
		// Distinguir el disparo del watchdog de una cancelación del caller.
		if streamCtx.Err() != nil && ctx.Err() == nil {
			return fmt.Errorf("deepseek: stream inactivo durante %s: %w", streamIdleTimeout, err)
		}
		return err
	}
	return nil
}
