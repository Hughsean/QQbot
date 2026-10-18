package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"qqtimeagent/internal/bootstrap"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := bootstrap.Run(ctx, os.Args[1:]); err != nil {
		slog.Error("application stopped", "reason", err.Error())
		os.Exit(1)
	}
}
