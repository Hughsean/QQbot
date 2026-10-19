package infrastructure

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"strings"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/secret"
)

type Fingerprinter struct{ key [32]byte }

func (Fingerprinter) String() string   { return "AccountFingerprinter([REDACTED])" }
func (Fingerprinter) GoString() string { return "AccountFingerprinter([REDACTED])" }

func NewFingerprinter(key secret.Value) (*Fingerprinter, error) {
	if len(key.Reveal()) < 32 {
		return nil, contracts.ErrInvalid
	}
	return &Fingerprinter{key: sha256.Sum256([]byte("account-fingerprint-v1|" + key.Reveal()))}, nil
}

func (f *Fingerprinter) Fingerprint(provider, identity string) (string, error) {
	identity = strings.TrimSpace(identity)
	if provider == "" || identity == "" {
		return "", contracts.ErrInvalid
	}
	h := hmac.New(sha256.New, f.key[:])
	_, _ = h.Write([]byte("v1|" + provider + "|" + identity))
	return "v1:" + hex.EncodeToString(h.Sum(nil)), nil
}
