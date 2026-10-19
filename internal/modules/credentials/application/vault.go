package application

import (
	"context"
	"time"

	"qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

type Vault struct {
	Repository Repository
	Cipher     Cipher
	Clock      clock.Clock
}

func (v Vault) Store(ctx context.Context, material secret.Value, kind contracts.Kind, expires *time.Time) (contracts.Ref, error) {
	now := v.Clock.Now()
	if !material.Present() || !kind.Valid() || now.IsZero() {
		return contracts.Ref{}, contracts.ErrInvalid
	}
	if expires != nil && !expires.After(now) {
		return contracts.Ref{}, contracts.ErrInvalid
	}
	id := ids.New()
	nonce, ciphertext, err := v.Cipher.Encrypt(id, kind, material)
	if err != nil {
		return contracts.Ref{}, err
	}
	err = v.Repository.Add(ctx, Record{ID: id, Kind: kind, KeyVersion: 1, Nonce: nonce, Ciphertext: ciphertext, CreatedAt: now, ExpiresAt: expires})
	if err != nil {
		return contracts.Ref{}, err
	}
	return contracts.Ref{ID: id}, nil
}

func (v Vault) Open(ctx context.Context, ref contracts.Ref) (contracts.Handle, error) {
	if ids.Validate(ref.ID) != nil {
		return contracts.Handle{}, contracts.ErrInvalid
	}
	record, err := v.Repository.Get(ctx, ref.ID)
	if err != nil {
		return contracts.Handle{}, err
	}
	now := v.Clock.Now()
	if now.IsZero() {
		return contracts.Handle{}, contracts.ErrInvalid
	}
	if record.ExpiresAt != nil && !now.Before(*record.ExpiresAt) {
		return contracts.Handle{}, contracts.ErrNotFound
	}
	material, err := v.Cipher.Decrypt(record)
	if err != nil {
		return contracts.Handle{}, err
	}
	expires := now.Add(time.Minute)
	if record.ExpiresAt != nil && record.ExpiresAt.Before(expires) {
		expires = *record.ExpiresAt
	}
	return contracts.NewHandle(material, record.Kind, &expires), nil
}

func (v Vault) Replace(ctx context.Context, ref contracts.Ref, material secret.Value) error {
	if ids.Validate(ref.ID) != nil || !material.Present() {
		return contracts.ErrInvalid
	}
	now := v.Clock.Now()
	if now.IsZero() {
		return contracts.ErrInvalid
	}
	record, err := v.Repository.Get(ctx, ref.ID)
	if err != nil {
		return err
	}
	if record.ExpiresAt != nil && !now.Before(*record.ExpiresAt) {
		return contracts.ErrNotFound
	}
	oldNonce := record.Nonce
	record.Nonce, record.Ciphertext, err = v.Cipher.Encrypt(record.ID, record.Kind, material)
	if err != nil {
		return err
	}
	record.KeyVersion, record.CreatedAt = 1, now
	return v.Repository.Replace(ctx, record, oldNonce)
}

func (v Vault) Delete(ctx context.Context, ref contracts.Ref) (bool, error) {
	if ids.Validate(ref.ID) != nil {
		return false, contracts.ErrInvalid
	}
	return v.Repository.Delete(ctx, ref.ID)
}

var _ contracts.Vault = Vault{}
