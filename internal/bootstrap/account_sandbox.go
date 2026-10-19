package bootstrap

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"time"

	"qqtimeagent/internal/adapters/inbound/accountprobe"
	"qqtimeagent/internal/adapters/outbound/microsoft"
	"qqtimeagent/internal/adapters/outbound/qqmail"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/secret"
)

type MicrosoftConfig struct {
	ClientID secret.Value
	Tenant   string
}
type MailSandboxConfig struct{ Address, Code secret.Value }

func runSandbox(ctx context.Context, cfg Config, role string) (bool, error) {
	switch role {
	case "qq-sandbox":
		return true, runQQSandbox(ctx, cfg)
	case "microsoft-sandbox":
		return true, runMicrosoftSandbox(ctx, cfg)
	case "qq-mail-sandbox":
		return true, runMailSandbox(ctx, cfg)
	default:
		return false, nil
	}
}

func runMicrosoftSandbox(ctx context.Context, cfg Config) error {
	if cfg.Container || cfg.ListenPort != 8000 {
		return errors.New("microsoft sandbox requires local loopback port 8000")
	}
	provider, err := microsoft.New(microsoft.Config{ClientID: cfg.Microsoft.ClientID.Reveal(), Tenant: cfg.Microsoft.Tenant, RedirectURI: "http://localhost:8000/oauth/microsoft/callback"}, clock.System{})
	if err != nil {
		return err
	}
	probe, err := accountprobe.New(provider, clock.System{})
	if err != nil {
		return err
	}
	return serveAccountProbe(ctx, probe)
}

func serveAccountProbe(ctx context.Context, probe *accountprobe.Probe) error {
	listener, err := net.Listen("tcp", "127.0.0.1:8000")
	if err != nil {
		return errors.New("microsoft sandbox loopback listener unavailable")
	}
	server := &http.Server{Handler: probe, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 65 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16384}
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	defer func() {
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	slog.Info("Microsoft sandbox ready", "entry", "http://localhost:8000")
	ctx, cancel := context.WithTimeout(ctx, 12*time.Minute)
	defer cancel()
	select {
	case err := <-probe.Done():
		return err
	case <-done:
		return errors.New("microsoft sandbox listener stopped")
	case <-ctx.Done():
		return errors.New("microsoft sandbox stopped before verification")
	}
}

func runMailSandbox(ctx context.Context, cfg Config) error {
	if !cfg.MailSandbox.Address.Present() || !cfg.MailSandbox.Code.Present() {
		return errors.New("QQ mail sandbox requires bootstrap address and authorization code")
	}
	verifier, err := qqmail.New(clock.System{})
	if err != nil {
		return err
	}
	if err := verifier.Verify(ctx, cfg.MailSandbox.Address, cfg.MailSandbox.Code); err != nil {
		return err
	}
	slog.Info("QQ mail sandbox passed", "tls", true, "login", true, "read_only_inbox", true)
	return nil
}
