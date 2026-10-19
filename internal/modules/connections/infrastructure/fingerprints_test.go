package infrastructure

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"testing"

	"qqtimeagent/internal/platform/secret"
)

func TestFingerprintLegacyCompatibilityAndValidation(t *testing.T) {
	signingKey := strings.Repeat("k", 32)
	f, err := NewFingerprinter(secret.New(signingKey))
	if err != nil {
		t.Fatal(err)
	}
	key := sha256.Sum256([]byte("account-fingerprint-v1|" + signingKey))
	mac := hmac.New(sha256.New, key[:])
	_, _ = mac.Write([]byte("v1|MICROSOFT|synthetic-account"))
	want := "v1:" + hex.EncodeToString(mac.Sum(nil))
	got, err := f.Fingerprint("MICROSOFT", " synthetic-account ")
	if err != nil || got != want {
		t.Fatal("legacy fingerprint mismatch")
	}
	if _, err := f.Fingerprint("", "identity"); err == nil {
		t.Fatal("empty provider accepted")
	}
	if _, err := f.Fingerprint("QQ_MAIL", " "); err == nil {
		t.Fatal("empty identity accepted")
	}
	if _, err := NewFingerprinter(secret.New("short")); err == nil {
		t.Fatal("short signing key accepted")
	}
	if fmt.Sprintf("%+v", *f) != "AccountFingerprinter([REDACTED])" || fmt.Sprintf("%#v", f) != "AccountFingerprinter([REDACTED])" {
		t.Fatal("derived signing key logged")
	}
}
