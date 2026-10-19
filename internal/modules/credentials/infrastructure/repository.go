package infrastructure

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"qqtimeagent/internal/modules/credentials/application"
	"qqtimeagent/internal/modules/credentials/contracts"
)

type Repository struct{ Pool *pgxpool.Pool }

func (r Repository) Add(ctx context.Context, record application.Record) error {
	_, err := r.Pool.Exec(ctx, `INSERT INTO credentials_vault_records
		(credential_id,kind,key_version,nonce,ciphertext,created_at,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7)`,
		record.ID, record.Kind, record.KeyVersion, record.Nonce, record.Ciphertext, record.CreatedAt, record.ExpiresAt)
	var pgError *pgconn.PgError
	if errors.As(err, &pgError) && pgError.Code == "23505" {
		return contracts.ErrConflict
	}
	if err != nil {
		return contracts.ErrStorage
	}
	return nil
}

func (r Repository) Get(ctx context.Context, id string) (application.Record, error) {
	record := application.Record{ID: id}
	err := r.Pool.QueryRow(ctx, `SELECT kind,key_version,nonce,ciphertext,created_at,expires_at
		FROM credentials_vault_records WHERE credential_id=$1`, id).Scan(&record.Kind, &record.KeyVersion, &record.Nonce, &record.Ciphertext, &record.CreatedAt, &record.ExpiresAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return application.Record{}, contracts.ErrNotFound
	}
	if err != nil {
		return application.Record{}, contracts.ErrStorage
	}
	return record, nil
}

func (r Repository) Replace(ctx context.Context, record application.Record, previousNonce []byte) error {
	result, err := r.Pool.Exec(ctx, `UPDATE credentials_vault_records SET nonce=$1,ciphertext=$2,
		key_version=$3,created_at=$4 WHERE credential_id=$5 AND nonce=$6`, record.Nonce, record.Ciphertext, record.KeyVersion, record.CreatedAt, record.ID, previousNonce)
	if err != nil {
		return contracts.ErrStorage
	}
	if result.RowsAffected() != 1 {
		return contracts.ErrConflict
	}
	return nil
}

func (r Repository) Delete(ctx context.Context, id string) (bool, error) {
	result, err := r.Pool.Exec(ctx, `DELETE FROM credentials_vault_records WHERE credential_id=$1`, id)
	if err != nil {
		return false, contracts.ErrStorage
	}
	return result.RowsAffected() == 1, nil
}

var _ application.Repository = Repository{}
