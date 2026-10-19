package infrastructure

import (
	"encoding/base64"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"

	"qqtimeagent/internal/modules/credentials/application"
	"qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/secret"
)

const fixtureID = "00000000-0000-4000-8000-000000000001"

// Generated independently by Python cryptography AESGCM, using synthetic data only.
func TestPythonAESGCMCompatibilityAndTamperRejection(t *testing.T) {
	key := make([]byte, 32)
	for i := range key {
		key[i] = byte(i)
	}
	cipher, err := NewAESGCM(secret.New(base64.URLEncoding.EncodeToString(key)))
	if err != nil {
		t.Fatal(err)
	}
	data, _ := hex.DecodeString("347bb86fad80b672ee6c73312300f8f7aea2e85f951508eb7865bb2026f562d693d20d633d8d")
	r := application.Record{ID: fixtureID, Kind: contracts.RefreshToken, KeyVersion: 1, Nonce: []byte{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}, Ciphertext: data}
	got, err := cipher.Decrypt(r)
	if err != nil || got.Reveal() != "synthetic-互通-token" {
		t.Fatal("Python fixture did not decrypt", err)
	}
	for _, mutate := range []func(*application.Record){
		func(r *application.Record) { r.ID = "00000000-0000-4000-8000-000000000002" },
		func(r *application.Record) { r.ID = "invalid" },
		func(r *application.Record) { r.Kind = contracts.AccessToken },
		func(r *application.Record) { r.Kind = "UNKNOWN" },
		func(r *application.Record) { r.KeyVersion = 2 },
		func(r *application.Record) { r.Nonce = r.Nonce[:11] },
		func(r *application.Record) { r.Ciphertext = []byte("tampered") },
	} {
		copy := r
		mutate(&copy)
		if _, err := cipher.Decrypt(copy); err == nil {
			t.Fatal("modified AAD/nonce/ciphertext accepted")
		}
	}
	first, ciphertext, err := cipher.Encrypt(fixtureID, contracts.RefreshToken, secret.New("synthetic-Go-fixture"))
	if err != nil {
		t.Fatal(err)
	}
	second, _, _ := cipher.Encrypt(fixtureID, contracts.RefreshToken, secret.New("synthetic-Go-fixture"))
	if string(first) == string(second) {
		t.Fatal("nonce reused")
	}
	// Optional output for independent Python verification; no production key or data.
	if output := os.Getenv("QQ_GO_SYNTHETIC_INTEROP_DIR"); output != "" {
		if err := os.WriteFile(filepath.Join(output, "go-aes-fixture.txt"), []byte(hex.EncodeToString(first)+"\n"+hex.EncodeToString(ciphertext)), 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestCipherKeyEncodingsAndInputValidation(t *testing.T) {
	key := []byte("kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk")
	for _, value := range []string{string(key), base64.URLEncoding.EncodeToString(key), base64.RawURLEncoding.EncodeToString(key)} {
		c, err := NewAESGCM(secret.New(value))
		if err != nil {
			t.Fatal(err)
		}
		for _, input := range []struct {
			id    string
			kind  contracts.Kind
			value string
		}{
			{"bad", contracts.RefreshToken, "synthetic"}, {fixtureID, "BAD", "synthetic"}, {fixtureID, contracts.RefreshToken, ""},
		} {
			if _, _, err := c.Encrypt(input.id, input.kind, secret.New(input.value)); err == nil {
				t.Fatal("invalid material accepted")
			}
		}
		raw := c.aead.Seal(nil, make([]byte, 12), []byte{0xff}, aad(fixtureID, contracts.RefreshToken))
		if _, err := c.Decrypt(application.Record{ID: fixtureID, Kind: contracts.RefreshToken, KeyVersion: 1, Nonce: make([]byte, 12), Ciphertext: raw}); err == nil {
			t.Fatal("invalid UTF-8 accepted")
		}
	}
	if _, err := NewAESGCM(secret.New("too-short")); err == nil {
		t.Fatal("short encryption key accepted")
	}
}
