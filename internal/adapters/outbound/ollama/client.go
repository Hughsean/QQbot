// Package ollama contains Provider DTOs and validates the active 1024-dimensional contract.
package ollama

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net/http"
	"strings"
	"time"

	"qqtimeagent/internal/modules/embeddings/contracts"
)

type Client struct {
	HTTP       *http.Client
	BaseURL    string
	Model      string
	Dimensions int
}

type embedRequest struct {
	Model      string   `json:"model"`
	Input      []string `json:"input"`
	Dimensions int      `json:"dimensions"`
	Truncate   bool     `json:"truncate"`
	KeepAlive  string   `json:"keep_alive"`
}

type embedResponse struct {
	Model      string      `json:"model"`
	Embeddings [][]float32 `json:"embeddings"`
}

func (c Client) Embed(ctx context.Context, texts []string) (contracts.Batch, error) {
	if len(texts) == 0 || len(texts) > 64 || c.Dimensions != 1024 {
		return contracts.Batch{}, errors.New("invalid embedding batch or dimensions")
	}
	for _, s := range texts {
		if strings.TrimSpace(s) == "" || len(s) > 800000 {
			return contracts.Batch{}, errors.New("embedding input is empty or exceeds limit")
		}
	}
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	payload, err := json.Marshal(embedRequest{c.Model, texts, c.Dimensions, false, "30m"})
	if err != nil {
		return contracts.Batch{}, errors.New("embedding encoding failed")
	}
	data, err := c.request(ctx, payload)
	if err != nil {
		return contracts.Batch{}, err
	}
	if err := c.validate(data, len(texts)); err != nil {
		return contracts.Batch{}, err
	}
	return contracts.Batch{Model: data.Model, Dimensions: c.Dimensions, Vectors: data.Embeddings}, nil
}

func (c Client) request(ctx context.Context, payload []byte) (embedResponse, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(c.BaseURL, "/")+"/api/embed", bytes.NewReader(payload))
	if err != nil {
		return embedResponse{}, errors.New("invalid embedding endpoint")
	}
	req.Header.Set("Content-Type", "application/json")
	client := c.HTTP
	if client == nil {
		client = &http.Client{Timeout: 60 * time.Second}
	}
	rsp, err := client.Do(req)
	if err != nil {
		return embedResponse{}, errors.New("embedding provider unavailable")
	}
	defer rsp.Body.Close()
	if rsp.StatusCode != http.StatusOK {
		return embedResponse{}, errors.New("embedding provider rejected request")
	}
	body, err := io.ReadAll(io.LimitReader(rsp.Body, 8*1024*1024+1))
	if err != nil || len(body) > 8*1024*1024 {
		return embedResponse{}, errors.New("invalid embedding response size")
	}
	var result embedResponse
	if json.Unmarshal(body, &result) != nil {
		return embedResponse{}, errors.New("invalid embedding JSON")
	}
	return result, nil
}

func (c Client) validate(data embedResponse, size int) error {
	if data.Model != c.Model || len(data.Embeddings) != size {
		return errors.New("embedding model or batch mismatch")
	}
	for _, vector := range data.Embeddings {
		if len(vector) != c.Dimensions {
			return errors.New("embedding dimension mismatch")
		}
		norm := float64(0)
		for _, n := range vector {
			norm += float64(n) * float64(n)
		}
		if norm == 0 || math.IsNaN(norm) || math.IsInf(norm, 0) {
			return errors.New("invalid embedding vector")
		}
	}
	return nil
}

func (c Client) Check(ctx context.Context) error {
	_, err := c.Embed(ctx, []string{"health probe"})
	return err
}

var _ contracts.Port = Client{}
