//go:build integration

package goaccounts

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"qqtimeagent/internal/adapters/outbound/postgres"
	"qqtimeagent/internal/platform/ids"
)

// Separate databases prevent interference with migration checksum-tamper tests.
// The endpoint and all test input are synthetic; .env is never consulted.
func database(t *testing.T) *pgxpool.Pool {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	endpoint := "127.0.0.1:55432"
	if os.Getenv("QQ_GO_TEST_CONTAINER") == "true" {
		endpoint = "postgres:5432"
	}
	dsn := "postgres://synthetic_go_test:synthetic-test-only@" + endpoint + "/qq_time_agent_go_test?sslmode=disable&timezone=UTC"
	admin, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal("synthetic database unavailable")
	}
	name := "go_accounts_" + strings.ReplaceAll(ids.New(), "-", "")
	identifier := pgx.Identifier{name}.Sanitize()
	if _, err := admin.Exec(ctx, "CREATE DATABASE "+identifier); err != nil {
		_ = admin.Close(ctx)
		t.Fatal("cannot create isolated synthetic database")
	}
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal(err)
	}
	config.ConnConfig.Database = name
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_, err := admin.Exec(ctx, "DROP DATABASE "+identifier+" WITH (FORCE)")
		_ = admin.Close(ctx)
		if err != nil {
			t.Error("cannot remove isolated test database")
		}
	})
	if err := postgres.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	return pool
}
