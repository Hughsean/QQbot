package infrastructure

import (
	"context"
	"encoding/json"

	"github.com/jackc/pgx/v5"
	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/modules/inbox/domain"
	"qqtimeagent/internal/platform/ids"
)

func (r Repository) Ingest(ctx context.Context, envelope domain.Envelope, raw contracts.RawContent) (result contracts.IngestResult, err error) {
	item, err := domain.Receive(ids.New(), ids.New(), envelope)
	if err != nil {
		return result, contracts.ErrInvalid
	}
	err = r.locked(ctx, envelope.ConnectionID, func(tx pgx.Tx) error {
		if err := writable(ctx, tx, envelope.ConnectionID); err != nil {
			return err
		}
		if err := notDeleted(ctx, tx, envelope); err != nil {
			return err
		}
		inserted, err := insertItem(ctx, tx, item)
		if err != nil {
			return err
		}
		if !inserted {
			result, err = findDuplicate(ctx, tx, envelope)
			return err
		}
		if err := insertRaw(ctx, tx, item, raw); err != nil {
			return err
		}
		result = contracts.IngestResult{ID: item.ID, Created: true, Status: string(item.Status), SourceRef: sourceRef(envelope.SourceType, envelope.ConnectionID, envelope.ExternalID)}
		return nil
	})
	return result, err
}

func notDeleted(ctx context.Context, tx pgx.Tx, e domain.Envelope) error {
	var deleted bool
	err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM inbox_source_deletions WHERE connection_id=$1
		AND (external_id=$2 OR ($3<>'' AND dedupe_key=$3)))`, e.ConnectionID, e.ExternalID, e.DedupeKey).Scan(&deleted)
	if err != nil {
		return contracts.ErrStorage
	}
	if deleted {
		return contracts.ErrDeleted
	}
	return nil
}

func insertItem(ctx context.Context, tx pgx.Tx, i domain.Item) (bool, error) {
	e := i.Envelope
	result, err := tx.Exec(ctx, `INSERT INTO inbox_items
		(inbox_item_id,connection_id,user_id,source_type,ingress_type,trust_level,external_id,dedupe_key,
		thread_id,sender_id,sender_display,occurred_at,received_at,raw_content_ref,content_hash,status,retry_count,version)
		VALUES ($1,$2,$3,$4,$5,$6,$7,NULLIF($8,''),NULLIF($9,''),$10,NULLIF($11,''),$12,$13,$14,$15,$16,0,1)
		ON CONFLICT DO NOTHING`, i.ID, e.ConnectionID, e.UserID, e.SourceType, e.IngressType, e.TrustLevel, e.ExternalID, e.DedupeKey,
		e.ThreadID, e.SenderID, e.SenderDisplay, e.OccurredAt, e.ReceivedAt, i.RawContentID, e.ContentHash, string(i.Status))
	if err != nil {
		return false, contracts.ErrStorage
	}
	return result.RowsAffected() == 1, nil
}

func insertRaw(ctx context.Context, tx pgx.Tx, i domain.Item, raw contracts.RawContent) error {
	recipients, _ := json.Marshal(append([]contracts.Address{}, raw.Recipients...))
	attachments, _ := json.Marshal(append([]contracts.AttachmentMetadata{}, raw.Attachments...))
	_, err := tx.Exec(ctx, `INSERT INTO inbox_raw_contents
		(raw_content_id,subject,body_text,body_html,mime_type,recipients,internet_message_id,change_key,
		has_attachments,attachment_metadata,created_at) VALUES($1,$2,$3,NULLIF($4,''),$5,$6,NULLIF($7,''),
		NULLIF($8,''),$9,$10,$11)`, i.RawContentID, raw.Subject, raw.BodyText, raw.BodyHTML, raw.MIMEType,
		recipients, raw.InternetMessageID, raw.ChangeKey, raw.HasAttachments, attachments, i.Envelope.ReceivedAt)
	return storageError(err)
}

func findDuplicate(ctx context.Context, tx pgx.Tx, e domain.Envelope) (contracts.IngestResult, error) {
	rows, err := tx.Query(ctx, `SELECT inbox_item_id::text,status,source_type,external_id FROM inbox_items
		WHERE connection_id=$1 AND (external_id=$2 OR ($3<>'' AND dedupe_key=$3)) LIMIT 2`, e.ConnectionID, e.ExternalID, e.DedupeKey)
	if err != nil {
		return contracts.IngestResult{}, contracts.ErrStorage
	}
	defer rows.Close()
	var result contracts.IngestResult
	count := 0
	for rows.Next() {
		var kind, external string
		if err := rows.Scan(&result.ID, &result.Status, &kind, &external); err != nil {
			return result, contracts.ErrStorage
		}
		result.SourceRef = sourceRef(kind, e.ConnectionID, external)
		count++
	}
	if rows.Err() != nil {
		return result, contracts.ErrStorage
	}
	if count != 1 {
		return contracts.IngestResult{}, contracts.ErrConflict
	}
	return result, nil
}
