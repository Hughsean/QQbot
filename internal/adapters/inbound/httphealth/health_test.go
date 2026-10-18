package httphealth

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type fixedProbe struct{ failed bool }

func (p fixedProbe) Check(context.Context) error {
	if p.failed {
		return errors.New("synthetic-provider-secret")
	}
	return nil
}

type cancelledProbe struct{}

func (cancelledProbe) Check(ctx context.Context) error { <-ctx.Done(); return ctx.Err() }

func TestHealthContracts(t *testing.T) {
	for _, failed := range []bool{false, true} {
		h := Handler{Database: fixedProbe{failed}, Embeddings: fixedProbe{}}.Routes()
		for _, path := range []string{"/health/live", "/health/ready"} {
			w := httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
			want := 200
			if path == "/health/ready" && failed {
				want = 503
			}
			if w.Code != want || strings.Contains(w.Body.String(), "synthetic-provider-secret") {
				t.Fatalf("health failed: %s", w.Body.String())
			}
		}
	}
}

func TestReadinessCancellationAndMissingProbe(t *testing.T) {
	for _, h := range []Handler{{}, {Database: cancelledProbe{}, Embeddings: cancelledProbe{}, Timeout: time.Millisecond}} {
		w := httptest.NewRecorder()
		h.Routes().ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/health/ready", nil))
		if w.Code != 503 {
			t.Fatal("unavailable dependency reported ready")
		}
	}
}
