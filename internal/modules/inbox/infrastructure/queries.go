package infrastructure

import (
	"context"
	"strings"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/modules/inbox/domain"
)

func (r Repository) Get(ctx context.Context, id string) (domain.Item, error) {
	var item domain.Item
	e := &item.Envelope
	err := r.Pool.QueryRow(ctx, `SELECT inbox_item_id::text,raw_content_ref::text,connection_id::text,
		user_id,source_type,ingress_type,trust_level,external_id,COALESCE(dedupe_key,''),COALESCE(thread_id,''),
		sender_id,COALESCE(sender_display,''),occurred_at,received_at,content_hash,status,
		COALESCE(failure_class,''),retry_count,version FROM inbox_items i WHERE inbox_item_id=$1 AND deleted_at IS NULL
		AND NOT EXISTS(SELECT 1 FROM inbox_connection_states s WHERE s.connection_id=i.connection_id AND s.blocked)`, id).
		Scan(&item.ID, &item.RawContentID, &e.ConnectionID, &e.UserID, &e.SourceType, &e.IngressType, &e.TrustLevel,
			&e.ExternalID, &e.DedupeKey, &e.ThreadID, &e.SenderID, &e.SenderDisplay, &e.OccurredAt, &e.ReceivedAt,
			&e.ContentHash, &item.Status, &item.FailureClass, &item.RetryCount, &item.Version)
	return item, storageError(err)
}

func (r Repository) Content(ctx context.Context, id string) (contracts.ContentView, error) {
	var value contracts.ContentView
	var kind, connectionID, externalID string
	err := r.Pool.QueryRow(ctx, `SELECT i.inbox_item_id::text,c.subject,c.body_text,COALESCE(c.body_html,''),c.mime_type,
		i.occurred_at,i.content_hash,i.source_type,i.connection_id::text,i.external_id
		FROM inbox_items i JOIN inbox_raw_contents c ON c.raw_content_id=i.raw_content_ref
		WHERE i.inbox_item_id=$1 AND i.deleted_at IS NULL AND NOT EXISTS
		(SELECT 1 FROM inbox_connection_states s WHERE s.connection_id=i.connection_id AND s.blocked)`, id).
		Scan(&value.ID, &value.Subject, &value.BodyText, &value.BodyHTML, &value.MIMEType, &value.OccurredAt,
			&value.ContentHash, &kind, &connectionID, &externalID)
	if err != nil {
		return contracts.ContentView{}, storageError(err)
	}
	value.SourceRef = sourceRef(kind, connectionID, externalID)
	return value, nil
}

func (r Repository) Source(ctx context.Context, id string) (contracts.SourceView, error) {
	var value contracts.SourceView
	var connectionID, sender string
	err := r.Pool.QueryRow(ctx, `SELECT i.inbox_item_id::text,i.source_type,i.external_id,COALESCE(i.thread_id,''),
		i.sender_id,c.subject,i.occurred_at,i.status,(i.deleted_at IS NOT NULL OR EXISTS
		(SELECT 1 FROM inbox_connection_states s WHERE s.connection_id=i.connection_id AND s.blocked)),i.connection_id::text
		FROM inbox_items i JOIN inbox_raw_contents c ON c.raw_content_id=i.raw_content_ref WHERE i.inbox_item_id=$1`, id).
		Scan(&value.ID, &value.SourceType, &value.ExternalID, &value.ThreadID, &sender, &value.Subject,
			&value.OccurredAt, &value.Status, &value.Deleted, &connectionID)
	if err != nil {
		return contracts.SourceView{}, storageError(err)
	}
	value.SourceRef = sourceRef(value.SourceType, connectionID, value.ExternalID)
	value.SenderMask = maskSender(sender)
	return value, nil
}

func maskSender(sender string) string {
	local, domain, ok := strings.Cut(sender, "@")
	if !ok {
		return "sender"
	}
	first := ""
	if runes := []rune(local); len(runes) > 0 {
		first = string(runes[0])
	}
	return first + "***@" + domain
}
