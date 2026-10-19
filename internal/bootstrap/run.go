package bootstrap

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"qqtimeagent/internal/adapters/inbound/httphealth"
	"qqtimeagent/internal/adapters/outbound/ollama"
	"qqtimeagent/internal/adapters/outbound/postgres"
)

func Run(ctx context.Context, args []string) error {
	role, err := parseRole(args)
	if err != nil {
		return err
	}
	cfg, err := LoadConfig(".env")
	if err != nil {
		return err
	}
	if role == "check-config" {
		return nil
	}
	if handled, err := runSandbox(ctx, cfg, role); handled {
		return err
	}
	if role == "healthcheck" {
		return checkLiveness(ctx, cfg.ListenPort)
	}
	if err := cfg.requireDatabase(); err != nil {
		return err
	}
	pool, err := pgxpool.New(ctx, cfg.Database.ConnectionString())
	if err != nil {
		return errors.New("database configuration rejected")
	}
	defer pool.Close()
	if role == "migrate" {
		ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
		defer cancel()
		return postgres.Migrate(ctx, pool)
	}
	return serve(ctx, cfg, pool)
}

func parseRole(args []string) (string, error) {
	if len(args) == 2 && args[1] == "--allow-account-read" && (args[0] == "microsoft-sandbox" || args[0] == "qq-mail-sandbox") {
		return args[0], nil
	}
	if len(args) == 2 && args[0] == "qq-sandbox" && args[1] == "--allow-send" {
		return "qq-sandbox", nil
	}
	if len(args) != 1 {
		return "", errors.New("usage: qq-time-agent <web|migrate|check-config|healthcheck|qq-sandbox --allow-send|microsoft-sandbox --allow-account-read|qq-mail-sandbox --allow-account-read>")
	}
	switch args[0] {
	case "web", "migrate", "check-config", "healthcheck":
		return args[0], nil
	default:
		return "", errors.New("unsupported role: Go Worker/QQ cutover requires remaining migration gates")
	}
}

func serve(ctx context.Context, cfg Config, pool *pgxpool.Pool) error {
	h := httphealth.Handler{Database: postgres.Probe{Pool: pool},
		Embeddings: ollama.Client{BaseURL: cfg.OllamaURL, Model: cfg.OllamaModel, Dimensions: cfg.Dimensions}}
	server := &http.Server{Addr: cfg.Address(), Handler: h.Routes(),
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second,
		WriteTimeout: 20 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16384}
	done := make(chan error, 1)
	go func() { done <- server.ListenAndServe() }()
	select {
	case err := <-done:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return errors.New("HTTP listener unavailable")
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return server.Shutdown(shutdown)
	}
}

func checkLiveness(ctx context.Context, port int) error {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, fmt.Sprintf("http://127.0.0.1:%d/health/live", port), nil)
	client := http.Client{Timeout: 3 * time.Second}
	rsp, err := client.Do(req)
	if err != nil {
		return errors.New("liveness unavailable")
	}
	defer rsp.Body.Close()
	if rsp.StatusCode != http.StatusOK {
		return errors.New("liveness rejected")
	}
	return nil
}
