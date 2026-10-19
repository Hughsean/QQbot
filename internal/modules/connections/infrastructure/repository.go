package infrastructure

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
)

type Repository struct{ Pool *pgxpool.Pool }

const columns = `connection_id::text,user_id,provider,status,COALESCE(provider_account_id,''),
	COALESCE(account_mask,''),COALESCE(account_fingerprint,''),display_label,is_default,sync_enabled,
	capabilities,COALESCE(credential_ref::text,''),last_synced_at,reauth_epoch,reauth_required_since,version`

type scanner interface{ Scan(...interface{}) error }

func readConnection(row scanner) (domain.Connection, error) {
	var c domain.Connection
	var capabilities []byte
	err := row.Scan(&c.ID, &c.UserID, &c.Provider, &c.Status, &c.AccountID, &c.AccountMask, &c.Fingerprint,
		&c.DisplayLabel, &c.Default, &c.SyncEnabled, &capabilities, &c.CredentialID, &c.LastSyncedAt, &c.ReauthEpoch, &c.ReauthSince, &c.Version)
	if errors.Is(err, pgx.ErrNoRows) {
		return c, contracts.ErrNotFound
	}
	if err != nil || json.Unmarshal(capabilities, &c.Capabilities) != nil {
		return domain.Connection{}, contracts.ErrStorage
	}
	return c, nil
}

func (r Repository) Get(ctx context.Context, id, user string) (domain.Connection, error) {
	return readConnection(r.Pool.QueryRow(ctx, `SELECT `+columns+` FROM connections_external_connections WHERE connection_id=$1 AND user_id=$2`, id, user))
}

func (r Repository) List(ctx context.Context, user string, provider domain.Provider) ([]domain.Connection, error) {
	rows, err := r.Pool.Query(ctx, `SELECT `+columns+` FROM connections_external_connections
		WHERE user_id=$1 AND provider=$2 ORDER BY is_default DESC,status,connection_id`, user, provider)
	if err != nil {
		return nil, contracts.ErrStorage
	}
	defer rows.Close()
	result := make([]domain.Connection, 0)
	for rows.Next() {
		c, err := readConnection(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, c)
	}
	if rows.Err() != nil {
		return nil, contracts.ErrStorage
	}
	return result, nil
}

func (r Repository) Add(ctx context.Context, c domain.Connection) error {
	return insertConnection(ctx, r.Pool, c)
}

type executor interface {
	Exec(context.Context, string, ...interface{}) (pgconn.CommandTag, error)
}

func values(c domain.Connection) []interface{} {
	capabilities, _ := json.Marshal(c.Capabilities)
	return []interface{}{c.ID, c.UserID, c.Provider, c.Status, c.AccountID, c.AccountMask, c.Fingerprint, c.DisplayLabel, c.Default, c.SyncEnabled, capabilities, c.CredentialID, c.LastSyncedAt, c.ReauthEpoch, c.ReauthSince, c.Version}
}

func insertConnection(ctx context.Context, db executor, c domain.Connection) error {
	_, err := db.Exec(ctx, `INSERT INTO connections_external_connections
		(connection_id,user_id,provider,status,provider_account_id,account_mask,account_fingerprint,display_label,is_default,sync_enabled,capabilities,credential_ref,last_synced_at,reauth_epoch,reauth_required_since,version)
		VALUES($1,$2,$3,$4,NULLIF($5,''),NULLIF($6,''),NULLIF($7,''),$8,$9,$10,$11,NULLIF($12,'')::uuid,$13,$14,$15,$16)`, values(c)...)
	return classifyStorage(err)
}

func (r Repository) Save(ctx context.Context, c domain.Connection, expected int) error {
	return saveConnection(ctx, r.Pool, c, expected)
}

func saveConnection(ctx context.Context, db executor, c domain.Connection, expected int) error {
	args := append(values(c), expected)
	result, err := db.Exec(ctx, `UPDATE connections_external_connections SET status=$4,provider_account_id=NULLIF($5,''),
		account_mask=NULLIF($6,''),account_fingerprint=NULLIF($7,''),display_label=$8,is_default=$9,sync_enabled=$10,
		capabilities=$11,credential_ref=NULLIF($12,'')::uuid,last_synced_at=$13,reauth_epoch=$14,reauth_required_since=$15,version=$16
		WHERE connection_id=$1 AND user_id=$2 AND provider=$3 AND version=$17`, args...)
	if err != nil {
		return classifyStorage(err)
	}
	if result.RowsAffected() != 1 {
		return contracts.ErrConflict
	}
	return nil
}

func classifyStorage(err error) error {
	if err == nil {
		return nil
	}
	var pgError *pgconn.PgError
	if errors.As(err, &pgError) && pgError.Code == "23505" {
		return contracts.ErrConflict
	}
	return contracts.ErrStorage
}

var _ application.Repository = Repository{}
