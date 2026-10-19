package infrastructure

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/modules/inbox/domain"
	"qqtimeagent/internal/platform/secret"
)

func (r Repository) Save(ctx context.Context, item domain.Item, expected int) error {
	if item.Version != expected+1 {
		return contracts.ErrConflict
	}
	return r.locked(ctx, item.Envelope.ConnectionID, func(tx pgx.Tx) error {
		if err := writable(ctx, tx, item.Envelope.ConnectionID); err != nil {
			return err
		}
		result, err := tx.Exec(ctx, `UPDATE inbox_items SET status=$1,failure_class=NULLIF($2,''),retry_count=$3,version=$4
			WHERE inbox_item_id=$5 AND connection_id=$6 AND version=$7 AND deleted_at IS NULL`,
			string(item.Status), item.FailureClass, item.RetryCount, item.Version, item.ID, item.Envelope.ConnectionID, expected)
		if err != nil {
			return contracts.ErrStorage
		}
		if result.RowsAffected() != 1 {
			return contracts.ErrConflict
		}
		return nil
	})
}

func (r Repository) SetBlocked(ctx context.Context, id string, blocked bool, now time.Time) error {
	if now.IsZero() {
		return contracts.ErrInvalid
	}
	return r.locked(ctx, id, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `INSERT INTO inbox_connection_states (connection_id,blocked,updated_at) VALUES($1,$2,$3)
			ON CONFLICT(connection_id) DO UPDATE SET blocked=EXCLUDED.blocked,updated_at=EXCLUDED.updated_at`, id, blocked, now)
		return storageError(err)
	})
}

func (r Repository) MarkDeleted(ctx context.Context, id, external string, now time.Time) (changed bool, err error) {
	if external == "" || now.IsZero() {
		return false, contracts.ErrInvalid
	}
	err = r.locked(ctx, id, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `INSERT INTO inbox_source_deletions(connection_id,external_id,dedupe_key,deleted_at)
			VALUES($1,$2::text,(SELECT dedupe_key FROM inbox_items WHERE connection_id=$1 AND external_id=$2::text),$3)
			ON CONFLICT DO NOTHING`, id, external, now)
		if err != nil {
			return contracts.ErrStorage
		}
		result, err := tx.Exec(ctx, `UPDATE inbox_items SET deleted_at=$3 WHERE connection_id=$1 AND external_id=$2 AND deleted_at IS NULL`, id, external, now)
		if err != nil {
			return contracts.ErrStorage
		}
		changed = result.RowsAffected() == 1
		return nil
	})
	return changed, err
}

func (r Repository) Cursor(ctx context.Context, id string) (secret.Value, error) {
	var value string
	err := r.Pool.QueryRow(ctx, `SELECT cursor_value FROM inbox_sync_cursors WHERE connection_id=$1`, id).Scan(&value)
	if err == pgx.ErrNoRows {
		return secret.Value{}, nil
	}
	if err != nil {
		return secret.Value{}, contracts.ErrStorage
	}
	return secret.New(value), nil
}

func (r Repository) SaveCursor(ctx context.Context, id string, cursor secret.Value, now time.Time) error {
	if !cursor.Present() || len(cursor.Reveal()) > 8192 || now.IsZero() {
		return contracts.ErrInvalid
	}
	return r.locked(ctx, id, func(tx pgx.Tx) error {
		if err := writable(ctx, tx, id); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `INSERT INTO inbox_sync_cursors(connection_id,cursor_value,updated_at) VALUES($1,$2,$3)
			ON CONFLICT(connection_id) DO UPDATE SET cursor_value=EXCLUDED.cursor_value,updated_at=EXCLUDED.updated_at`, id, cursor.Reveal(), now)
		return storageError(err)
	})
}
