package bootstrap

import (
	"context"
	"log/slog"
	"time"

	"qqtimeagent/internal/adapters/qq"
)

func runQQSandbox(ctx context.Context, cfg Config) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Minute)
	defer cancel()
	return qq.Sandbox(ctx, qq.SandboxConfig{
		AppID: cfg.QQ.AppID, AppSecret: cfg.QQ.AppSecret, Owner: cfg.QQ.Owner,
		Sandbox: cfg.QQ.Sandbox, AllowSend: true,
	}, slog.Default())
}
