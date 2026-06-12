package tinyfish

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

const (
	SearchURL = "https://api.search.tinyfish.ai"
	FetchURL  = "https://api.fetch.tinyfish.ai"
)

type Client struct {
	apiKey     string
	httpClient *http.Client
}

func NewClient(apiKey string) *Client {
	return &Client{
		apiKey: apiKey,
		httpClient: &http.Client{
			Timeout: 150 * time.Second,
		},
	}
}

type SearchResult struct {
	Position int    `json:"position"`
	SiteName string `json:"site_name"`
	Title    string `json:"title"`
	Snippet  string `json:"snippet"`
	URL      string `json:"url"`
}

type SearchResponse struct {
	Query        string         `json:"query"`
	Results      []SearchResult `json:"results"`
	TotalResults int            `json:"total_results"`
	Page         int            `json:"page"`
}

func (c *Client) Search(ctx context.Context, query string) (*SearchResponse, error) {
	u, _ := url.Parse(SearchURL)
	q := u.Query()
	q.Set("query", query)
	u.RawQuery = q.Encode()

	req, err := http.NewRequestWithContext(ctx, "GET", u.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("tinyfish search: %w", err)
	}
	req.Header.Set("X-API-Key", c.apiKey)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("tinyfish search: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("tinyfish search: HTTP %d", resp.StatusCode)
	}

	var result SearchResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("tinyfish search: decode: %w", err)
	}
	return &result, nil
}

type FetchResult struct {
	URL      string `json:"url"`
	FinalURL string `json:"final_url"`
	Title    string `json:"title"`
	Text     string `json:"text"`
}

type FetchResponse struct {
	Results []FetchResult `json:"results"`
	Errors  []struct {
		URL   string `json:"url"`
		Error string `json:"error"`
	} `json:"errors"`
}

func (c *Client) FetchContent(ctx context.Context, urls []string) (*FetchResponse, error) {
	body, _ := json.Marshal(map[string]interface{}{
		"urls":   urls,
		"format": "markdown",
	})

	req, err := http.NewRequestWithContext(ctx, "POST", FetchURL, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("tinyfish fetch: %w", err)
	}
	req.Header.Set("X-API-Key", c.apiKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("tinyfish fetch: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("tinyfish fetch: HTTP %d", resp.StatusCode)
	}

	var result FetchResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("tinyfish fetch: decode: %w", err)
	}
	return &result, nil
}
