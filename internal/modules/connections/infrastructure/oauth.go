package infrastructure

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
)

func (r Repository) AddAuthorization(ctx context.Context, c domain.Connection, expected int, t domain.OAuthTransaction) error {
	tx, err := r.Pool.Begin(ctx)
	if err != nil {
		return contracts.ErrStorage
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if expected == 0 {
		err = insertConnection(ctx, tx, c)
	} else {
		err = saveConnection(ctx, tx, c, expected)
	}
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO connections_oauth_transactions
		(transaction_id,connection_id,user_id,state_hash,browser_session_hash,flow_credential_ref,expires_at,created_at)
		VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, t.ID, t.ConnectionID, t.UserID, t.StateHash, t.BrowserHash, t.FlowCredentialID, t.ExpiresAt, t.CreatedAt)
	if err != nil {
		return classifyStorage(err)
	}
	if err := tx.Commit(ctx); err != nil {
		return contracts.ErrStorage
	}
	return nil
}

// One UPDATE atomically consumes the state, fenced by browser hash and expiry.
func (r Repository) ClaimTransaction(ctx context.Context, state, browser []byte, now time.Time) (domain.OAuthTransaction, error) {
	if len(state) != 32 || len(browser) != 32 || now.IsZero() {
		return domain.OAuthTransaction{}, contracts.ErrSecurity
	}
	var t domain.OAuthTransaction
	err := r.Pool.QueryRow(ctx, `UPDATE connections_oauth_transactions SET consumed_at=$3
		WHERE state_hash=$1 AND browser_session_hash=$2 AND consumed_at IS NULL AND expires_at>$3
		RETURNING transaction_id::text,connection_id::text,user_id,state_hash,browser_session_hash,flow_credential_ref::text,expires_at,created_at,consumed_at`, state, browser, now).
		Scan(&t.ID, &t.ConnectionID, &t.UserID, &t.StateHash, &t.BrowserHash, &t.FlowCredentialID, &t.ExpiresAt, &t.CreatedAt, &t.ConsumedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.OAuthTransaction{}, contracts.ErrSecurity
	}
	if err != nil {
		return domain.OAuthTransaction{}, contracts.ErrStorage
	}
	return t, nil
}

func (r Repository) SaveDisconnected(ctx context.Context, c domain.Connection, expected int, now time.Time) error {
	if c.Status != domain.Disconnected || now.IsZero() {
		return contracts.ErrInvalid
	}
	tx, err := r.Pool.Begin(ctx)
	if err != nil {
		return contracts.ErrStorage
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if err := saveConnection(ctx, tx, c, expected); err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `UPDATE connections_oauth_transactions SET consumed_at=$2 WHERE connection_id=$1 AND consumed_at IS NULL`, c.ID, now)
	if err != nil {
		return contracts.ErrStorage
	}
	if err := tx.Commit(ctx); err != nil {
		return contracts.ErrStorage
	}
	return nil
}
