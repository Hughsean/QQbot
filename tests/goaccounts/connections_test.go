//go:build integration

package goaccounts

import (
	"bytes"
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	"qqtimeagent/internal/modules/connections/infrastructure"
	"qqtimeagent/internal/platform/ids"
)

func TestConnectionIsolationUniqueIdentityAndVersions(t *testing.T) {
	pool := database(t)
	ctx := context.Background()
	repo := infrastructure.Repository{Pool: pool}
	c, _ := domain.Start(ids.New(), "owner", domain.Microsoft)
	if err := repo.Add(ctx, c); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.Get(ctx, c.ID, "other"); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("owner isolation bypassed")
	}
	c.BindIdentity("v1:synthetic", "masked", true)
	c.Activate("account", "masked", []string{"Mail.Read"}, ids.New())
	if err := repo.Save(ctx, c, 1); err != nil {
		t.Fatal(err)
	}
	if err := repo.Save(ctx, c, 1); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("stale version accepted")
	}
	copy, _ := repo.Get(ctx, c.ID, "owner")
	if copy.Version != 2 || copy.AccountID != "account" || len(copy.Capabilities) != 1 {
		t.Fatal("roundtrip lost state")
	}
	duplicate, _ := domain.Start(ids.New(), "owner", domain.Microsoft)
	duplicate.BindIdentity("v1:synthetic", "mask", false)
	if err := repo.Add(ctx, duplicate); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("duplicate active identity accepted")
	}
	duplicate.Fingerprint = "v1:different"
	duplicate.Activate("other", "mask", []string{"Mail.Read"}, ids.New())
	duplicate.Default = true
	if err := repo.Add(ctx, duplicate); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("two defaults accepted")
	}
	duplicate.Default = false
	if err := repo.Add(ctx, duplicate); err != nil {
		t.Fatal(err)
	}
	mail, _ := domain.Start(ids.New(), "owner", domain.QQMail)
	if err := repo.Add(ctx, mail); err != nil {
		t.Fatal(err)
	}
	values, err := repo.List(ctx, "owner", domain.Microsoft)
	if err != nil || len(values) != 2 || values[0].ID != c.ID {
		t.Fatal("provider list isolation failed")
	}
	if values, err := repo.List(ctx, "other", domain.Microsoft); err != nil || len(values) != 0 {
		t.Fatal("list leaked another owner")
	}
	c.Disconnect(true)
	if err := repo.Save(ctx, c, 2); err != nil {
		t.Fatal(err)
	}
	duplicate.Fingerprint = "v1:synthetic"
	duplicate.Version++
	if err := repo.Save(ctx, duplicate, 2); err != nil {
		t.Fatal("disconnected identity could not be reused", err)
	}
	pool.Close()
	if _, err := repo.Get(ctx, c.ID, "owner"); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if _, err := repo.List(ctx, "owner", domain.Microsoft); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if err := repo.Add(ctx, c); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if err := repo.Save(ctx, c, 3); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
}

func TestOAuthAtomicClaimAndAuthorizationRollback(t *testing.T) {
	pool := database(t)
	ctx := context.Background()
	repo := infrastructure.Repository{Pool: pool}
	now := time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)
	c, _ := domain.Start(ids.New(), "owner", domain.Microsoft)
	flow := domain.OAuthTransaction{ID: ids.New(), ConnectionID: c.ID, UserID: "owner", StateHash: bytes.Repeat([]byte{1}, 32), BrowserHash: bytes.Repeat([]byte{2}, 32), FlowCredentialID: ids.New(), CreatedAt: now, ExpiresAt: now.Add(time.Minute)}
	if err := repo.AddAuthorization(ctx, c, 0, flow); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.ClaimTransaction(ctx, flow.StateHash, bytes.Repeat([]byte{9}, 32), now); !errors.Is(err, contracts.ErrSecurity) {
		t.Fatal("wrong browser claimed state")
	}
	for _, when := range []time.Time{time.Time{}, flow.ExpiresAt} {
		if _, err := repo.ClaimTransaction(ctx, flow.StateHash, flow.BrowserHash, when); err == nil {
			t.Fatal("invalid time accepted")
		}
	}
	if _, err := repo.ClaimTransaction(ctx, nil, flow.BrowserHash, now); err == nil {
		t.Fatal("invalid hash accepted")
	}
	var wg sync.WaitGroup
	var winners atomic.Int32
	for range 16 {
		wg.Go(func() {
			got, err := repo.ClaimTransaction(ctx, flow.StateHash, flow.BrowserHash, now)
			if err == nil {
				if got.ConnectionID != c.ID || !got.ConsumedAt.Equal(now) {
					t.Error("claim metadata lost")
				}
				winners.Add(1)
			} else if !errors.Is(err, contracts.ErrSecurity) {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	if winners.Load() != 1 {
		t.Fatalf("OAuth callback had %d winners", winners.Load())
	}
	other, _ := domain.Start(ids.New(), "owner", domain.Microsoft)
	flow.ID = ids.New()
	flow.ConnectionID = other.ID
	if err := repo.AddAuthorization(ctx, other, 0, flow); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("duplicate state accepted")
	}
	if _, err := repo.Get(ctx, other.ID, "owner"); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("failed authorization left orphan connection")
	}
	c.Version++
	flow.ID = ids.New()
	flow.ConnectionID = c.ID
	flow.StateHash = bytes.Repeat([]byte{3}, 32)
	if err := repo.AddAuthorization(ctx, c, 99, flow); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("stale begin accepted")
	}
	if err := repo.AddAuthorization(ctx, c, 1, flow); err != nil {
		t.Fatal(err)
	}
	before := c.Version
	if err := repo.SaveDisconnected(ctx, c, before, now); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("non-disconnected state accepted")
	}
	c.Disconnect(true)
	if err := repo.SaveDisconnected(ctx, c, before, time.Time{}); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("zero disconnect time accepted")
	}
	if err := repo.SaveDisconnected(ctx, c, 99, now); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("stale disconnect accepted")
	}
	if err := repo.SaveDisconnected(ctx, c, before, now); err != nil {
		t.Fatal("atomic disconnect failed", err)
	}
	if _, err := repo.ClaimTransaction(ctx, flow.StateHash, flow.BrowserHash, now); !errors.Is(err, contracts.ErrSecurity) {
		t.Fatal("disconnect did not revoke pending authorization")
	}
	pool.Close()
	if err := repo.SaveDisconnected(ctx, c, before, now); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("disconnect storage error hidden")
	}
	if err := repo.AddAuthorization(ctx, c, 2, flow); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if _, err := repo.ClaimTransaction(ctx, flow.StateHash, flow.BrowserHash, now); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("database outage misclassified as bad callback")
	}
}
