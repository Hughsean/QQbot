package application_test

import (
	"bytes"
	"context"
	"encoding/gob"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/credentials/application"
	"qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/modules/credentials/infrastructure"
	"qqtimeagent/internal/platform/secret"
)

type fixedClock struct{ now time.Time }

func (c *fixedClock) Now() time.Time { return c.now }

type memory struct {
	rows     map[string]application.Record
	fail     error
	conflict bool
}

func (m *memory) Add(_ context.Context, r application.Record) error {
	if m.fail != nil {
		return m.fail
	}
	m.rows[r.ID] = r
	return nil
}
func (m *memory) Get(_ context.Context, id string) (application.Record, error) {
	if m.fail != nil {
		return application.Record{}, m.fail
	}
	r, ok := m.rows[id]
	if !ok {
		return r, contracts.ErrNotFound
	}
	return r, nil
}
func (m *memory) Replace(_ context.Context, r application.Record, old []byte) error {
	if m.conflict || !bytes.Equal(m.rows[r.ID].Nonce, old) {
		return contracts.ErrConflict
	}
	m.rows[r.ID] = r
	return nil
}
func (m *memory) Delete(_ context.Context, id string) (bool, error) {
	if m.fail != nil {
		return false, m.fail
	}
	_, ok := m.rows[id]
	delete(m.rows, id)
	return ok, nil
}

func fixture(t *testing.T) (application.Vault, *memory, *fixedClock) {
	t.Helper()
	cipher, err := infrastructure.NewAESGCM(secret.New(strings.Repeat("k", 32)))
	if err != nil {
		t.Fatal(err)
	}
	m := &memory{rows: map[string]application.Record{}}
	c := &fixedClock{time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)}
	return application.Vault{Repository: m, Cipher: cipher, Clock: c}, m, c
}

func TestVaultEncryptRotateExpireDelete(t *testing.T) {
	v, m, c := fixture(t)
	ctx := context.Background()
	expires := c.now.Add(time.Minute)
	ref, err := v.Store(ctx, secret.New("synthetic-one"), contracts.RefreshToken, &expires)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(m.rows[ref.ID].Ciphertext, []byte("synthetic-one")) {
		t.Fatal("plaintext persisted")
	}
	h, err := v.Open(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	value, err := h.Reveal(c.now)
	if err != nil || value.Reveal() != "synthetic-one" {
		t.Fatal("material mismatch")
	}
	if h.Kind() != contracts.RefreshToken {
		t.Fatal("kind lost")
	}
	for _, encoded := range []string{fmt.Sprint(h), fmt.Sprintf("%#v", h)} {
		if strings.Contains(encoded, "synthetic-one") {
			t.Fatal("handle leaked")
		}
	}
	if _, err := json.Marshal(h); err == nil {
		t.Fatal("JSON serialization accepted")
	}
	if _, err := h.MarshalText(); err == nil {
		t.Fatal("text serialization accepted")
	}
	var buf bytes.Buffer
	if err := gob.NewEncoder(&buf).Encode(h); err == nil {
		t.Fatal("gob serialization accepted")
	}
	buf.Reset()
	slog.New(slog.NewJSONHandler(&buf, nil)).Info("handle", "value", h)
	if strings.Contains(buf.String(), "synthetic-one") {
		t.Fatal("log leaked")
	}
	before := m.rows[ref.ID]
	if err := v.Replace(ctx, ref, secret.New("synthetic-two")); err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(before.Nonce, m.rows[ref.ID].Nonce) {
		t.Fatal("replacement reused nonce")
	}
	h, _ = v.Open(ctx, ref)
	value, _ = h.Reveal(c.now)
	if value.Reveal() != "synthetic-two" {
		t.Fatal("rotation lost")
	}
	m.conflict = true
	if !errors.Is(v.Replace(ctx, ref, secret.New("synthetic-three")), contracts.ErrConflict) {
		t.Fatal("CAS conflict hidden")
	}
	m.conflict = false
	c.now = expires
	if _, err := h.Reveal(c.now); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("expired handle usable")
	}
	if _, err := v.Open(ctx, ref); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("expired record opened")
	}
	if err := v.Replace(ctx, ref, secret.New("synthetic")); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("expired record replaced")
	}
	if ok, err := v.Delete(ctx, ref); err != nil || !ok {
		t.Fatal("deletion failed")
	}
	if ok, err := v.Delete(ctx, ref); err != nil || ok {
		t.Fatal("deletion not idempotent")
	}
	if _, err := v.Open(ctx, ref); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("deleted credential opened")
	}
}

type failingCipher struct{}

func (failingCipher) Encrypt(string, contracts.Kind, secret.Value) ([]byte, []byte, error) {
	return nil, nil, contracts.ErrInvalid
}
func (failingCipher) Decrypt(application.Record) (secret.Value, error) {
	return secret.Value{}, contracts.ErrInvalid
}

func TestVaultRejectsInvalidAndPropagatesFailures(t *testing.T) {
	v, m, c := fixture(t)
	ctx := context.Background()
	now := c.now
	for _, input := range []struct {
		s      string
		k      contracts.Kind
		expiry *time.Time
	}{{"", contracts.RefreshToken, nil}, {"synthetic", "BAD", nil}, {"synthetic", contracts.OAuthFlow, &now}} {
		if _, err := v.Store(ctx, secret.New(input.s), input.k, input.expiry); !errors.Is(err, contracts.ErrInvalid) {
			t.Fatal("invalid credential accepted")
		}
	}
	for _, id := range []string{"bad", "00000000-0000-4000-8000-000000000009"} {
		ref := contracts.Ref{ID: id}
		if _, err := v.Open(ctx, ref); err == nil {
			t.Fatal("missing ref opened")
		}
		if err := v.Replace(ctx, ref, secret.New("synthetic")); err == nil {
			t.Fatal("missing ref replaced")
		}
	}
	if _, err := v.Delete(ctx, contracts.Ref{ID: "bad"}); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("bad ID accepted")
	}
	ref, err := v.Store(ctx, secret.New("synthetic"), contracts.OAuthFlow, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := v.Replace(ctx, ref, secret.New("")); err == nil {
		t.Fatal("empty replacement accepted")
	}
	v.Cipher = failingCipher{}
	if _, err := v.Store(ctx, secret.New("synthetic"), contracts.RefreshToken, nil); err == nil {
		t.Fatal("encryption failure hidden")
	}
	if _, err := v.Open(ctx, ref); err == nil {
		t.Fatal("decryption failure hidden")
	}
	if err := v.Replace(ctx, ref, secret.New("synthetic")); err == nil {
		t.Fatal("replacement failure hidden")
	}
	m.fail = contracts.ErrStorage
	if _, err := v.Open(ctx, ref); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("read failure hidden")
	}
	if err := v.Replace(ctx, ref, secret.New("synthetic")); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("read failure hidden")
	}
	v, _, c = fixture(t)
	v.Repository = m
	if _, err := v.Store(ctx, secret.New("synthetic"), contracts.RefreshToken, nil); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("write failure hidden")
	}
	c.now = time.Time{}
	if _, err := v.Store(ctx, secret.New("synthetic"), contracts.RefreshToken, nil); err == nil {
		t.Fatal("zero clock accepted")
	}
	if _, err := (contracts.Handle{}).Reveal(now); err == nil {
		t.Fatal("zero handle accepted")
	}
	if _, err := contracts.NewHandle(secret.New("synthetic"), contracts.RefreshToken, nil).Reveal(time.Time{}); err == nil {
		t.Fatal("zero reveal time accepted")
	}
}
