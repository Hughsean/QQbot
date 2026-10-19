package application

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"strings"
	"time"

	"qqtimeagent/internal/modules/identity/contracts"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/secret"
)

type Sessions struct {
	key   secret.Value
	clock clock.Clock
}
type sessionPayload struct {
	Subject string `json:"sub"`
	Expires int64  `json:"exp"`
	ID      string `json:"jti"`
}

func NewSessions(key secret.Value, timeSource clock.Clock) (*Sessions, error) {
	if len(key.Reveal()) < 32 || timeSource == nil {
		return nil, contracts.ErrInvalid
	}
	return &Sessions{key: key, clock: timeSource}, nil
}

func (s *Sessions) signature(encoded string) string {
	h := hmac.New(sha256.New, []byte(s.key.Reveal()))
	_, _ = h.Write([]byte(encoded))
	return base64.RawURLEncoding.EncodeToString(h.Sum(nil))
}

func (s *Sessions) Issue(user string, lifetime time.Duration) (secret.Value, error) {
	if user != "owner" || lifetime <= 0 || lifetime > time.Hour || s.clock.Now().IsZero() {
		return secret.Value{}, contracts.ErrInvalid
	}
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		return secret.Value{}, contracts.ErrInvalid
	}
	payload := sessionPayload{Subject: user, Expires: s.clock.Now().Add(lifetime).Unix(), ID: base64.RawURLEncoding.EncodeToString(nonce)}
	data, err := json.Marshal(payload)
	if err != nil {
		return secret.Value{}, contracts.ErrInvalid
	}
	encoded := base64.RawURLEncoding.EncodeToString(data)
	return secret.New(encoded + "." + s.signature(encoded)), nil
}

func (s *Sessions) Verify(token secret.Value) (contracts.Session, error) {
	if len(token.Reveal()) > 4096 {
		return contracts.Session{}, contracts.ErrSecurity
	}
	encoded, signature, ok := strings.Cut(token.Reveal(), ".")
	if !ok || !hmac.Equal([]byte(signature), []byte(s.signature(encoded))) {
		return contracts.Session{}, contracts.ErrSecurity
	}
	data, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return contracts.Session{}, contracts.ErrSecurity
	}
	var payload sessionPayload
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&payload) != nil || decoder.Decode(new(json.RawMessage)) != io.EOF {
		return contracts.Session{}, contracts.ErrSecurity
	}
	if !s.validSession(payload) {
		return contracts.Session{}, contracts.ErrSecurity
	}
	if payload.Subject != "owner" {
		return contracts.Session{}, contracts.ErrForbidden
	}
	return contracts.Session{UserID: payload.Subject, ExpiresAt: time.Unix(payload.Expires, 0).UTC()}, nil
}

func (s *Sessions) validSession(p sessionPayload) bool {
	now := s.clock.Now()
	return !now.IsZero() && p.Subject != "" && len(p.ID) >= 16 && p.Expires > now.Unix() && p.Expires <= now.Add(time.Hour).Unix()
}

var _ contracts.SessionAuthority = (*Sessions)(nil)
