package application

import (
	"context"
	"time"

	"qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/secret"
)

type Record struct {
	ID         string
	Kind       contracts.Kind
	KeyVersion int
	Nonce      []byte
	Ciphertext []byte
	CreatedAt  time.Time
	ExpiresAt  *time.Time
}

type Repository interface {
	Add(context.Context, Record) error
	Get(context.Context, string) (Record, error)
	Replace(context.Context, Record, []byte) error
	Delete(context.Context, string) (bool, error)
}

type Cipher interface {
	Encrypt(string, contracts.Kind, secret.Value) ([]byte, []byte, error)
	Decrypt(Record) (secret.Value, error)
}
