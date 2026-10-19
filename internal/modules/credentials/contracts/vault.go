// Package contracts exposes encrypted-storage references and expiring, nonserializable handles.
package contracts

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"qqtimeagent/internal/platform/secret"
)

type Kind string

const (
	OAuthFlow    Kind = "OAUTH_FLOW"
	RefreshToken Kind = "REFRESH_TOKEN"
	AccessToken  Kind = "ACCESS_TOKEN"
	IMAPAuthCode Kind = "IMAP_AUTH_CODE"
)

var (
	ErrNotFound = errors.New("credential unavailable or expired")
	ErrConflict = errors.New("credential was replaced concurrently")
	ErrInvalid  = errors.New("invalid credential")
	ErrStorage  = errors.New("credential persistence failed")
)

func (k Kind) Valid() bool {
	switch k {
	case OAuthFlow, RefreshToken, AccessToken, IMAPAuthCode:
		return true
	default:
		return false
	}
}

type Ref struct{ ID string }

type Handle struct {
	material secret.Value
	kind     Kind
	expires  *time.Time
}

func NewHandle(material secret.Value, kind Kind, expires *time.Time) Handle {
	if expires != nil {
		value := *expires
		expires = &value
	}
	return Handle{material: material, kind: kind, expires: expires}
}

func (h Handle) Reveal(now time.Time) (secret.Value, error) {
	if now.IsZero() || !h.kind.Valid() || !h.material.Present() {
		return secret.Value{}, ErrInvalid
	}
	if h.expires != nil && !now.Before(*h.expires) {
		return secret.Value{}, ErrNotFound
	}
	return h.material, nil
}

func (h Handle) Kind() Kind     { return h.kind }
func (Handle) String() string   { return "CredentialHandle([REDACTED])" }
func (Handle) GoString() string { return "CredentialHandle([REDACTED])" }
func (Handle) MarshalJSON() ([]byte, error) {
	return nil, errors.New("credential handles cannot be serialized")
}
func (Handle) MarshalText() ([]byte, error) {
	return nil, errors.New("credential handles cannot be serialized")
}
func (Handle) GobEncode() ([]byte, error) {
	return nil, errors.New("credential handles cannot be serialized")
}
func (Handle) LogValue() slog.Value { return slog.StringValue("CredentialHandle([REDACTED])") }

type Vault interface {
	Store(context.Context, secret.Value, Kind, *time.Time) (Ref, error)
	Open(context.Context, Ref) (Handle, error)
	Replace(context.Context, Ref, secret.Value) error
	Delete(context.Context, Ref) (bool, error)
}
