//go:build integration

package gosources

import (
	"context"
	"errors"
	"strconv"
	"sync"
	"testing"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/platform/ids"
)

func TestInboxDeletionRacingIngestAlwaysWinsFinalVisibility(t *testing.T) {
	_, repo, s := inbox(t)
	ctx := context.Background()
	conn := ids.New()
	now := sourceClock{}.Now()
	for index := range 20 {
		external := "raced-" + strconv.Itoa(index)
		var wg sync.WaitGroup
		wg.Go(func() {
			_, err := s.IngestMail(ctx, conn, "owner", "QQ_MAIL", mailChange(external))
			if err != nil && !errors.Is(err, contracts.ErrDeleted) {
				t.Error(err)
			}
		})
		wg.Go(func() {
			if _, err := repo.MarkDeleted(ctx, conn, external, now); err != nil {
				t.Error(err)
			}
		})
		wg.Wait()
		if _, err := s.IngestMail(ctx, conn, "owner", "QQ_MAIL", mailChange(external)); !errors.Is(err, contracts.ErrDeleted) {
			t.Fatal("delete/ingest race resurrected source")
		}
	}
}

func TestInboxConflictingExternalAndSecondaryKeysAreRejected(t *testing.T) {
	pool, _, s := inbox(t)
	ctx := context.Background()
	conn := ids.New()
	a := mailChange("external-a")
	a.DedupeKey = "key-a"
	b := mailChange("external-b")
	b.DedupeKey = "key-b"
	if _, err := s.IngestMail(ctx, conn, "owner", "QQ_MAIL", a); err != nil {
		t.Fatal(err)
	}
	if _, err := s.IngestMail(ctx, conn, "owner", "QQ_MAIL", b); err != nil {
		t.Fatal(err)
	}
	a.DedupeKey = b.DedupeKey
	if _, err := s.IngestMail(ctx, conn, "owner", "QQ_MAIL", a); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("ambiguous source identity silently selected a row")
	}
	var items, raws int
	if err := pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM inbox_items),(SELECT count(*) FROM inbox_raw_contents)`).Scan(&items, &raws); err != nil || items != 2 || raws != 2 {
		t.Fatal("identity conflict changed raw data")
	}
}
