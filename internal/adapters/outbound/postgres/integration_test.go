//go:build integration

package postgres

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"qqtimeagent/internal/platform/jobs"
)

// Hard-coded synthetic endpoint prevents accidental access to real .env/databases.
const integrationDSN = "postgres://synthetic_go_test:synthetic-test-only@127.0.0.1:55432/qq_time_agent_go_test?sslmode=disable&timezone=UTC"

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := integrationDSN
	if os.Getenv("QQ_GO_TEST_CONTAINER") == "true" {
		dsn = "postgres://synthetic_go_test:synthetic-test-only@postgres:5432/qq_time_agent_go_test?sslmode=disable&timezone=UTC"
	}
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal("cannot configure isolated test pool")
	}
	t.Cleanup(pool.Close)
	if err := Migrate(context.Background(), pool); err != nil {
		t.Fatal(err)
	}
	return pool
}

func TestIntegrationBaselineAndExtensionReadiness(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	if err := Migrate(ctx, pool); err != nil {
		t.Fatal("migration is not idempotent", err)
	}
	if err := (Probe{pool}).Check(ctx); err != nil {
		t.Fatal(err)
	}
	var tables int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM information_schema.tables WHERE table_schema='public'`).Scan(&tables); err != nil || tables != 50 {
		t.Fatalf("unexpected table inventory %d: %v", tables, err)
	}
	_, err := pool.Exec(ctx, `UPDATE go_schema_migrations SET checksum='synthetic-modified'`)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		sql, _ := migrations.ReadFile("migrations/0001_initial_schema.sql")
		_, _ = pool.Exec(ctx, `UPDATE go_schema_migrations SET checksum=$1`, baselineChecksum(sql))
	})
	if err := Migrate(ctx, pool); err == nil {
		t.Fatal("modified baseline accepted")
	}
}

func TestIntegrationConcurrentEnqueueAndLeaseFencing(t *testing.T) {
	pool := testPool(t)
	queue := JobQueue{pool}
	ctx := context.Background()
	now := time.Date(2026, 10, 18, 0, 0, 0, 0, time.UTC)
	var wg sync.WaitGroup
	ids, failures := make(chan string, 16), make(chan error, 16)
	key := "synthetic-concurrent-" + strings.ReplaceAll(t.Name(), "/", "-")
	_, _ = pool.Exec(ctx, `DELETE FROM platform_jobs WHERE kind='synthetic-test'`)
	for index := range 16 {
		wg.Go(func() {
			id, err := queue.Enqueue(ctx, jobs.Request{ID: fmt.Sprintf("00000000-0000-4000-8000-%012d", index+1), Kind: "synthetic-test", Payload: []byte(`{"reference":"synthetic"}`), IdempotencyKey: key, AvailableAt: now, MaxAttempts: 3})
			if err != nil {
				failures <- err
				return
			}
			ids <- id
		})
	}
	wg.Wait()
	close(ids)
	close(failures)
	for err := range failures {
		t.Fatal(err)
	}
	var first string
	for id := range ids {
		if first == "" {
			first = id
		}
		if first != id {
			t.Fatal("concurrent idempotency created duplicate jobs")
		}
	}
	if first == "" {
		t.Fatal("no job enqueued")
	}
	leases, err := queue.LeaseDue(ctx, now, "synthetic-worker-a", []string{"synthetic-test"}, 10, time.Minute)
	if err != nil || len(leases) != 1 {
		t.Fatalf("cannot lease due job: %v", err)
	}
	if other, err := queue.LeaseDue(ctx, now, "synthetic-worker-b", []string{"synthetic-test"}, 10, time.Minute); err != nil || len(other) != 0 {
		t.Fatal("concurrent lease duplicated work")
	}
	if other, err := queue.LeaseDue(ctx, now, "synthetic-worker-b", []string{"unmigrated-kind"}, 10, time.Minute); err != nil || len(other) != 0 {
		t.Fatal("claimed unmigrated job kind")
	}
	later := now.Add(2 * time.Minute)
	recovered, err := queue.LeaseDue(ctx, later, "synthetic-worker-b", []string{"synthetic-test"}, 10, time.Minute)
	if err != nil || len(recovered) != 1 || recovered[0].Attempt != 2 {
		t.Fatal("expired lease not recovered")
	}
	if err := queue.Complete(ctx, leases[0], later); !errors.Is(err, jobs.ErrStaleLease) {
		t.Fatal("stale worker overwrote new lease")
	}
	if err := queue.Complete(ctx, recovered[0], later); err != nil {
		t.Fatal(err)
	}
	if err := queue.Complete(ctx, recovered[0], later); !errors.Is(err, jobs.ErrStaleLease) {
		t.Fatal("duplicate completion accepted")
	}
}

func TestIntegrationRetryDeadLetterAndInvalidRequests(t *testing.T) {
	pool := testPool(t)
	q := JobQueue{pool}
	ctx := context.Background()
	now := time.Date(2026, 10, 18, 0, 0, 0, 0, time.UTC)
	_, _ = pool.Exec(ctx, `DELETE FROM platform_jobs WHERE kind='synthetic-retry'`)
	r := jobs.Request{ID: "00000000-0000-4000-8000-000000000099", Kind: "synthetic-retry", Payload: []byte(`{}`), IdempotencyKey: "synthetic-retry-test", AvailableAt: now, MaxAttempts: 2}
	if _, err := q.Enqueue(ctx, r); err != nil {
		t.Fatal(err)
	}
	leases, err := q.LeaseDue(ctx, now, "synthetic-worker", []string{r.Kind}, 1, time.Minute)
	if err != nil || len(leases) != 1 {
		t.Fatal("cannot lease retry test")
	}
	retry := now.Add(10 * time.Second)
	if q.Fail(ctx, leases[0], now, "", &retry) == nil {
		t.Fatal("invalid error class accepted")
	}
	if err := q.Fail(ctx, leases[0], now, "TransientProvider", &retry); err != nil {
		t.Fatal(err)
	}
	if early, _ := q.LeaseDue(ctx, now, "synthetic-worker", []string{r.Kind}, 1, time.Minute); len(early) != 0 {
		t.Fatal("retry ran early")
	}
	leases, err = q.LeaseDue(ctx, retry, "synthetic-worker", []string{r.Kind}, 1, time.Minute)
	if err != nil || len(leases) != 1 {
		t.Fatal("retry not available")
	}
	if err := q.Fail(ctx, leases[0], retry, "TransientProvider", &retry); err != nil {
		t.Fatal(err)
	}
	var status string
	if err := pool.QueryRow(ctx, `SELECT status FROM platform_jobs WHERE job_id=$1`, r.ID).Scan(&status); err != nil || status != "DEAD_LETTER" {
		t.Fatal("exhausted retry not dead-lettered")
	}
	if _, err := q.Enqueue(ctx, jobs.Request{}); err == nil {
		t.Fatal("invalid job accepted")
	}
	if _, err := q.LeaseDue(ctx, now, "", nil, 0, 0); err == nil {
		t.Fatal("invalid lease request accepted")
	}
	if q.Complete(ctx, leases[0], time.Time{}) == nil {
		t.Fatal("missing time accepted")
	}
}

func TestIntegrationRefusesUnverifiedLegacyDatabase(t *testing.T) {
	admin := testPool(t)
	ctx := context.Background()
	random := make([]byte, 8)
	if _, err := rand.Read(random); err != nil {
		t.Fatal(err)
	}
	name := "synthetic_go_legacy_" + hex.EncodeToString(random)
	identifier := pgx.Identifier{name}.Sanitize()
	if _, err := admin.Exec(ctx, "CREATE DATABASE "+identifier); err != nil {
		t.Fatal("cannot create synthetic legacy database")
	}
	t.Cleanup(func() { _, _ = admin.Exec(ctx, "DROP DATABASE "+identifier+" WITH (FORCE)") })
	config := admin.Config()
	config.ConnConfig.Database = name
	legacy, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(legacy.Close)
	sql, _ := migrations.ReadFile("migrations/0001_initial_schema.sql")
	if _, err := legacy.Exec(ctx, string(sql)); err != nil {
		t.Fatal("legacy baseline failed")
	}
	if err := Migrate(ctx, legacy); err == nil || !strings.Contains(err.Error(), "verified Go adoption") {
		t.Fatal("unverified adoption was not blocked")
	}
	var ledger bool
	if err := legacy.QueryRow(ctx, `SELECT to_regclass('public.go_schema_migrations') IS NOT NULL`).Scan(&ledger); err != nil || ledger {
		t.Fatal("refused adoption modified database")
	}
}
