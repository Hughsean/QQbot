package infrastructure

import (
	"context"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/platform/ids"
)

type Repository struct{ Pool *pgxpool.Pool }

func (r Repository) locked(ctx context.Context, connectionID string, operation func(pgx.Tx) error) error {
	if ids.Validate(connectionID) != nil {
		return contracts.ErrInvalid
	}
	tx, err := r.Pool.Begin(ctx)
	if err != nil {
		return contracts.ErrStorage
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock($1)`, lockKey(connectionID)); err != nil {
		return contracts.ErrStorage
	}
	if err := operation(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return contracts.ErrStorage
	}
	return nil
}

func lockKey(id string) int64 {
	data, _ := hex.DecodeString(strings.ReplaceAll(id, "-", ""))
	value := binary.BigEndian.Uint64(data[8:]) & ((1 << 63) - 1)
	if value >= 1<<62 {
		return int64(value | (1 << 63))
	}
	return int64(value)
}

func writable(ctx context.Context, tx pgx.Tx, id string) error {
	var blocked bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM inbox_connection_states WHERE connection_id=$1 AND blocked)`, id).Scan(&blocked); err != nil {
		return contracts.ErrStorage
	}
	if blocked {
		return contracts.ErrDeleted
	}
	return nil
}

func sourceRef(kind, connectionID, externalID string) string {
	prefix := "mail"
	switch kind {
	case "QQ_MAIL":
		prefix = "qq-mail"
	case "QQ_DIRECT":
		prefix = "qq"
	case "QQ_FORWARD":
		prefix = "qq-forward"
	case "OWNER_NOTE":
		prefix = "owner-note"
	}
	return prefix + ":" + connectionID + ":" + externalID
}

func storageError(err error) error {
	if errors.Is(err, pgx.ErrNoRows) {
		return contracts.ErrNotFound
	}
	if err != nil {
		return contracts.ErrStorage
	}
	return nil
}
