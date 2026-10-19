package infrastructure

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"qqtimeagent/internal/modules/normalization/contracts"
)

type Repository struct{ Pool *pgxpool.Pool }

func (r Repository) Upsert(ctx context.Context, value contracts.Content) error {
	_, err := r.Pool.Exec(ctx, `INSERT INTO normalization_contents
		(inbox_item_id,subject,body,source_hash,normalizer_version,source_ref)
		VALUES ($1,$2,$3,$4,$5,NULLIF($6,'')) ON CONFLICT (inbox_item_id) DO UPDATE SET
		subject=EXCLUDED.subject,body=EXCLUDED.body,source_hash=EXCLUDED.source_hash,
		normalizer_version=EXCLUDED.normalizer_version,source_ref=EXCLUDED.source_ref`,
		value.InboxItemID, value.Subject, value.Body, value.SourceHash, value.NormalizerVersion, value.SourceRef)
	if err != nil {
		return contracts.ErrStorage
	}
	return nil
}

func (r Repository) Get(ctx context.Context, id string) (contracts.Content, error) {
	var value contracts.Content
	err := r.Pool.QueryRow(ctx, `SELECT inbox_item_id::text,subject,body,source_hash,normalizer_version,
		COALESCE(source_ref,'') FROM normalization_contents WHERE inbox_item_id=$1`, id).
		Scan(&value.InboxItemID, &value.Subject, &value.Body, &value.SourceHash, &value.NormalizerVersion, &value.SourceRef)
	if errors.Is(err, pgx.ErrNoRows) {
		return contracts.Content{}, nil
	}
	if err != nil {
		return contracts.Content{}, contracts.ErrStorage
	}
	return value, nil
}
