//go:build integration

package gosources

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"

	"qqtimeagent/internal/modules/normalization/application"
	"qqtimeagent/internal/modules/normalization/contracts"
	"qqtimeagent/internal/modules/normalization/infrastructure"
	"qqtimeagent/internal/platform/ids"
)

func TestNormalizationPersistenceIdempotenceAndSourceMetadata(t *testing.T) {
	pool := database(t)
	repo := infrastructure.Repository{Pool: pool}
	s, err := application.New(repo, infrastructure.HTMLText{})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	id := ids.New()
	input := contracts.Input{InboxItemID: id, Subject: "  Weekly   review  ", BodyHTML: "<script>hidden</script><p>Hello &amp; welcome</p>", SourceHash: strings.Repeat("a", 64), SourceRef: "mail:synthetic"}
	var wg sync.WaitGroup
	for range 12 {
		wg.Go(func() {
			if _, err := s.Normalize(ctx, input); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	var count int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM normalization_contents WHERE inbox_item_id=$1`, id).Scan(&count); err != nil || count != 1 {
		t.Fatal("normalization upsert duplicated rows", err)
	}
	v, err := s.Get(ctx, id)
	if err != nil || v.Body != "Hello & welcome" || v.Subject != "Weekly review" || v.SourceHash != input.SourceHash || v.SourceRef != input.SourceRef || v.NormalizerVersion != "mail-text-v1" {
		t.Fatal("stored normalized content mismatch", err)
	}
	input.BodyText = "new body"
	input.SourceHash = strings.Repeat("b", 64)
	input.SourceRef = ""
	if _, err := s.Normalize(ctx, input); err != nil {
		t.Fatal(err)
	}
	v, err = s.Get(ctx, id)
	if err != nil || v.Body != "new body" || v.SourceRef != "" || v.SourceHash != input.SourceHash {
		t.Fatal("version replacement or nullable source ref failed")
	}
	if missing, err := s.Get(ctx, ids.New()); err != nil || missing.InboxItemID != "" {
		t.Fatal("missing query changed")
	}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if err := repo.Upsert(cancelled, v); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("SQL error leaked or hidden")
	}
	if _, err := repo.Get(cancelled, id); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("SQL query error leaked or hidden")
	}
}
