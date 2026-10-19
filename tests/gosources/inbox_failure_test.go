//go:build integration

package gosources

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/modules/inbox/domain"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

func TestInboxRollbackAndInvalidCursorWritesFailClosed(t *testing.T) {
	pool, repo, s := inbox(t)
	ctx := context.Background()
	now := sourceClock{}.Now()
	conn := ids.New()
	for _, cursor := range []secret.Value{secret.Value{}, secret.New(strings.Repeat("x", 8193))} {
		if err := repo.SaveCursor(ctx, conn, cursor, now); !errors.Is(err, contracts.ErrInvalid) {
			t.Fatal("invalid cursor accepted")
		}
	}
	if err := repo.SaveCursor(ctx, conn, secret.New("valid"), time.Time{}); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("zero cursor time accepted")
	}
	if err := repo.SetBlocked(ctx, conn, true, time.Time{}); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("zero fence time accepted")
	}
	if err := repo.SetBlocked(ctx, "invalid", true, now); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("invalid fence ID accepted")
	}
	if _, err := repo.MarkDeleted(ctx, conn, "", now); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("empty deletion identity accepted")
	}
	if _, err := repo.MarkDeleted(ctx, conn, "external", time.Time{}); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("zero deletion time accepted")
	}
	if value, err := repo.Cursor(ctx, conn); err != nil || value.Present() {
		t.Fatal("missing cursor changed")
	}
	if _, err := repo.Content(ctx, ids.New()); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("missing content changed")
	}
	if _, err := repo.Source(ctx, ids.New()); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("missing source changed")
	}
	if _, err := repo.Get(ctx, ids.New()); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("missing item changed")
	}
	e := domain.Envelope{ConnectionID: conn, UserID: "owner", ExternalID: "rollback", SenderID: "a@example.test", ContentHash: strings.Repeat("a", 64), SourceType: "MICROSOFT_MAIL", IngressType: "SYNC", TrustLevel: "T2", OccurredAt: now, ReceivedAt: now}
	if _, err := repo.Ingest(ctx, e, contracts.RawContent{MIMEType: strings.Repeat("x", 81)}); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("invalid SQL content was not rejected")
	}
	var count int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM inbox_items`).Scan(&count); err != nil || count != 0 {
		t.Fatal("failed raw insert left an orphan Inbox item")
	}
	if _, err := repo.Ingest(ctx, domain.Envelope{}, contracts.RawContent{}); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("invalid envelope reached SQL")
	}
	item, err := s.IngestMail(ctx, conn, "owner", "MICROSOFT_MAIL", mailChange("live"))
	if err != nil {
		t.Fatal(err)
	}
	if err := repo.SetBlocked(ctx, conn, true, now); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.Content(ctx, item.ID); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("blocked content still visible")
	}
	if source, err := repo.Source(ctx, item.ID); err != nil || !source.Deleted {
		t.Fatal("blocked source did not show unavailable")
	}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if err := repo.SetBlocked(cancelled, conn, false, now); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("cancelled fence committed")
	}
	if _, err := repo.Cursor(cancelled, conn); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("cancelled cursor read hidden")
	}
}
