package ollama

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestEmbeddingContract(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/embed" || r.Method != "POST" {
			t.Error("bad endpoint")
		}
		var request embedRequest
		if json.NewDecoder(r.Body).Decode(&request) != nil || request.Dimensions != 1024 || request.Truncate {
			t.Error("invalid request")
		}
		vector := make([]float32, 1024)
		vector[0] = 1
		_ = json.NewEncoder(w).Encode(embedResponse{Model: "synthetic-model", Embeddings: [][]float32{vector}})
	}))
	defer server.Close()
	c := Client{BaseURL: server.URL, Model: "synthetic-model", Dimensions: 1024}
	batch, err := c.Embed(context.Background(), []string{"test"})
	if err != nil || batch.Dimensions != 1024 || len(batch.Vectors) != 1 {
		t.Fatalf("embedding rejected: %v", err)
	}
	if c.Check(context.Background()) != nil {
		t.Fatal("health probe failed")
	}
}

func TestEmbeddingRejectsInvalidInputsAndProviderOutput(t *testing.T) {
	cases := []struct {
		name, body string
		status     int
	}{
		{"wrong-model", `{"model":"other","embeddings":[[1]]}`, 200},
		{"wrong-dimensions", `{"model":"synthetic-model","embeddings":[[1]]}`, 200},
		{"missing-vectors", `{"model":"synthetic-model","embeddings":[]}`, 200},
		{"invalid-json", `not-json`, 200}, {"provider-failure", `synthetic-sensitive`, 500},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer server.Close()
			c := Client{BaseURL: server.URL, Model: "synthetic-model", Dimensions: 1024}
			if _, err := c.Embed(context.Background(), []string{"test"}); err == nil {
				t.Fatal("invalid provider response accepted")
			}
		})
	}
	c := Client{Dimensions: 1024}
	for _, texts := range [][]string{nil, {""}, {"   "}} {
		if _, err := c.Embed(context.Background(), texts); err == nil {
			t.Fatal("invalid input accepted")
		}
	}
	if c.validate(embedResponse{Model: "test", Embeddings: [][]float32{make([]float32, 1024)}}, 1) == nil {
		t.Fatal("model mismatch accepted")
	}
	c.Model = "test"
	if c.validate(embedResponse{Model: "test", Embeddings: [][]float32{make([]float32, 1024)}}, 1) == nil {
		t.Fatal("zero vector accepted")
	}
}
