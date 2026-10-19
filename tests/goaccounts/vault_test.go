//go:build integration

package goaccounts

import (
	"context"
	"errors"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"qqtimeagent/internal/modules/credentials/application"
	"qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/modules/credentials/infrastructure"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

type fixedClock struct{ now time.Time }

func (c fixedClock) Now() time.Time { return c.now }

func TestCredentialPersistenceCASAndExpiry(t *testing.T) {
	pool := database(t)
	ctx := context.Background()
	now := time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)
	repo := infrastructure.Repository{Pool: pool}
	cipher, err := infrastructure.NewAESGCM(secret.New(strings.Repeat("s", 32)))
	if err != nil {
		t.Fatal(err)
	}
	vault := application.Vault{Repository: repo, Cipher: cipher, Clock: fixedClock{now}}
	expires := now.Add(time.Minute)
	ref, err := vault.Store(ctx, secret.New("synthetic-integration-token"), contracts.RefreshToken, &expires)
	if err != nil {
		t.Fatal(err)
	}
	record, err := repo.Get(ctx, ref.ID)
	if err != nil {
		t.Fatal(err)
	}
	if record.Kind != contracts.RefreshToken || !record.CreatedAt.Equal(now) || !record.ExpiresAt.Equal(expires) {
		t.Fatal("credential metadata changed")
	}
	if strings.Contains(string(record.Ciphertext), "synthetic-integration-token") {
		t.Fatal("plaintext persisted")
	}
	if !errors.Is(repo.Add(ctx, record), contracts.ErrConflict) {
		t.Fatal("duplicate credential ID accepted")
	}
	var winners atomic.Int32
	var wg sync.WaitGroup
	for range 16 {
		wg.Go(func() {
			replacement := record
			replacement.Nonce, replacement.Ciphertext, _ = cipher.Encrypt(record.ID, record.Kind, secret.New("synthetic-rotated"))
			err := repo.Replace(ctx, replacement, record.Nonce)
			if err == nil {
				winners.Add(1)
			} else if !errors.Is(err, contracts.ErrConflict) {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	if winners.Load() != 1 {
		t.Fatalf("CAS had %d winners", winners.Load())
	}
	if err := vault.Replace(ctx, ref, secret.New("synthetic-current")); err != nil {
		t.Fatal(err)
	}
	h, err := vault.Open(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	material, err := h.Reveal(now)
	if err != nil || material.Reveal() != "synthetic-current" {
		t.Fatal("persisted rotation lost")
	}
	vault.Clock = fixedClock{expires}
	if _, err := vault.Open(ctx, ref); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("expired record opened")
	}
	if ok, err := vault.Delete(ctx, ref); err != nil || !ok {
		t.Fatal("delete failed", err)
	}
	if ok, err := vault.Delete(ctx, ref); err != nil || ok {
		t.Fatal("delete not idempotent", err)
	}
	if _, err := repo.Get(ctx, ids.New()); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("missing credential not classified")
	}
	if _, err := repo.Get(ctx, "invalid"); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("driver error not sanitized")
	}
	pool.Close()
	if _, err := repo.Get(ctx, ref.ID); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage failure hidden")
	}
	if err := repo.Add(ctx, record); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage failure hidden")
	}
	if err := repo.Replace(ctx, record, record.Nonce); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage failure hidden")
	}
	if _, err := repo.Delete(ctx, ref.ID); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage failure hidden")
	}
}
