// Package httphealth preserves the existing health endpoint contracts.
package httphealth

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"time"
)

type Probe interface{ Check(context.Context) error }

type Handler struct {
	Database   Probe
	Embeddings Probe
	Timeout    time.Duration
}

type response struct {
	Status       string          `json:"status"`
	Dependencies map[string]bool `json:"dependencies,omitempty"`
}

func (h Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health/live", func(w http.ResponseWriter, _ *http.Request) {
		write(w, http.StatusOK, response{Status: "ok"})
	})
	mux.HandleFunc("GET /health/ready", h.ready)
	return mux
}

func (h Handler) ready(w http.ResponseWriter, r *http.Request) {
	timeout := h.Timeout
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()
	var wg sync.WaitGroup
	var database, embeddings bool
	wg.Go(func() { database = h.Database != nil && h.Database.Check(ctx) == nil })
	wg.Go(func() { embeddings = h.Embeddings != nil && h.Embeddings.Check(ctx) == nil })
	wg.Wait()
	code, status := http.StatusOK, "ready"
	if !database || !embeddings {
		code, status = http.StatusServiceUnavailable, "not_ready"
	}
	write(w, code, response{Status: status, Dependencies: map[string]bool{
		"database": database, "embeddings": embeddings,
	}})
}

func write(w http.ResponseWriter, code int, value response) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(value)
}
