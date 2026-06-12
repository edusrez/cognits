package rag

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

var httpClient = &http.Client{Timeout: 60 * time.Second}

type Client struct {
	baseURL string
}

func NewClient(baseURL string) *Client {
	return &Client{baseURL: baseURL}
}

type ChunkInput struct {
	ID         string `json:"id"`
	Text       string `json:"text"`
	ReportID   string `json:"report_id"`
	SourceType string `json:"source_type"`
	ChunkIndex int    `json:"chunk_index"`
	Topic      string `json:"topic"`
}

type SearchResult struct {
	ID         string  `json:"id"`
	Text       string  `json:"text"`
	Distance   float64 `json:"distance"`
	ReportID   string  `json:"report_id"`
	SourceType string  `json:"source_type"`
	Topic      string  `json:"topic"`
	ChunkIndex int     `json:"chunk_index"`
}

func (c *Client) Health(ctx context.Context) (int, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/health", nil)
	if err != nil {
		return 0, err
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()

	var result struct {
		Status string `json:"status"`
		Docs   int    `json:"docs"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return 0, fmt.Errorf("rag: decode health: %w", err)
	}
	if result.Status != "ok" {
		return 0, fmt.Errorf("rag: unhealthy status: %s", result.Status)
	}
	return result.Docs, nil
}

func (c *Client) Embed(ctx context.Context, texts []string) ([][]float32, error) {
	body, err := json.Marshal(map[string]any{"texts": texts})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/embed", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("rag: embed request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("rag: embed failed (%d): %s", resp.StatusCode, string(b))
	}

	var result struct {
		Embeddings [][]float32 `json:"embeddings"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("rag: decode embed: %w", err)
	}
	return result.Embeddings, nil
}

func (c *Client) Search(ctx context.Context, query string, maxResults int) ([]SearchResult, error) {
	if maxResults <= 0 {
		maxResults = 10
	}
	body, err := json.Marshal(map[string]any{
		"query":       query,
		"max_results": maxResults,
	})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/search", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("rag: search request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("rag: search failed (%d): %s", resp.StatusCode, string(b))
	}

	var result struct {
		Chunks []SearchResult `json:"chunks"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("rag: decode search: %w", err)
	}
	return result.Chunks, nil
}

func (c *Client) Index(ctx context.Context, chunks []ChunkInput) (int, error) {
	body, err := json.Marshal(map[string]any{"chunks": chunks})
	if err != nil {
		return 0, err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/index", bytes.NewReader(body))
	if err != nil {
		return 0, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return 0, fmt.Errorf("rag: index request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return 0, fmt.Errorf("rag: index failed (%d): %s", resp.StatusCode, string(b))
	}

	var result struct {
		Indexed int `json:"indexed"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return 0, fmt.Errorf("rag: decode index: %w", err)
	}
	return result.Indexed, nil
}
