package postgres

import (
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed migrations/*.sql migrations/*.json
var migrations embed.FS

const baseline = "0001_initial_schema"

// Migrate initializes empty databases atomically and refuses unverified adoption.
// Existing Python databases require G10 schema/data comparison before cutover.
func Migrate(ctx context.Context, pool *pgxpool.Pool) error {
	tx, err := pool.Begin(ctx)
	if err != nil {
		return errors.New("migration database unavailable")
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if _, err = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(788810017)"); err != nil {
		return errors.New("migration lock unavailable")
	}
	sql, err := migrations.ReadFile("migrations/0001_initial_schema.sql")
	if err != nil {
		return errors.New("migration artifact missing")
	}
	checksum := baselineChecksum(sql)
	var tables int
	err = tx.QueryRow(ctx, `SELECT count(*) FROM information_schema.tables
		WHERE table_schema='public' AND table_type='BASE TABLE'`).Scan(&tables)
	if err != nil {
		return errors.New("cannot inspect database schema")
	}
	if tables != 0 {
		if err := verifyMigration(ctx, tx, checksum); err != nil {
			return err
		}
		return commitMigration(ctx, tx)
	}
	if err := initializeSchema(ctx, tx, string(sql), checksum); err != nil {
		return err
	}
	return commitMigration(ctx, tx)
}

func baselineChecksum(sql []byte) string {
	digest := sha256.Sum256(sql)
	return hex.EncodeToString(digest[:])
}

func commitMigration(ctx context.Context, tx pgx.Tx) error {
	if err := tx.Commit(ctx); err != nil {
		return errors.New("migration commit failed")
	}
	return nil
}

func initializeSchema(ctx context.Context, tx pgx.Tx, sql, checksum string) error {
	if _, err := tx.Exec(ctx, sql); err != nil {
		return errors.New("baseline DDL failed")
	}
	if _, err := tx.Exec(ctx, `CREATE TABLE go_schema_migrations
		(version text PRIMARY KEY, checksum text NOT NULL)`); err != nil {
		return errors.New("migration ledger creation failed")
	}
	if _, err := tx.Exec(ctx, "INSERT INTO go_schema_migrations VALUES ($1,$2)", baseline, checksum); err != nil {
		return errors.New("migration ledger write failed")
	}
	return nil
}

func verifyMigration(ctx context.Context, tx pgx.Tx, checksum string) error {
	var ledgerExists bool
	if err := tx.QueryRow(ctx, "SELECT to_regclass('public.go_schema_migrations') IS NOT NULL").Scan(&ledgerExists); err != nil {
		return errors.New("cannot inspect migration ledger")
	}
	if !ledgerExists {
		return errors.New("existing database requires verified Go adoption; schema was not changed")
	}
	if err := verifyLedger(ctx, tx, checksum); err != nil {
		return err
	}
	var original string
	if err := tx.QueryRow(ctx, "SELECT version_num FROM alembic_version").Scan(&original); err != nil || original != baseline {
		return errors.New("incompatible original schema baseline")
	}
	return nil
}

func verifyLedger(ctx context.Context, tx pgx.Tx, checksum string) error {
	var version, stored string
	rows, err := tx.Query(ctx, "SELECT version, checksum FROM go_schema_migrations")
	if err != nil {
		return errors.New("cannot read migration ledger")
	}
	defer rows.Close()
	count := 0
	for rows.Next() {
		if err := rows.Scan(&version, &stored); err != nil {
			return errors.New("invalid migration ledger")
		}
		count++
	}
	if rows.Err() != nil || count != 1 || version != baseline || stored != checksum {
		return errors.New("unknown or modified Go migration baseline")
	}
	return nil
}
