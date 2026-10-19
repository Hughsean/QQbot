package infrastructure

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"unicode/utf8"

	"qqtimeagent/internal/modules/credentials/application"
	"qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

type AESGCM struct{ aead cipher.AEAD }

func NewAESGCM(encoded secret.Value) (*AESGCM, error) {
	key, err := decodeKey(encoded.Reveal())
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, contracts.ErrInvalid
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, contracts.ErrInvalid
	}
	return &AESGCM{aead: aead}, nil
}

func decodeKey(value string) ([]byte, error) {
	for _, encoding := range []*base64.Encoding{base64.URLEncoding, base64.RawURLEncoding} {
		if key, err := encoding.DecodeString(value); err == nil && len(key) == 32 {
			return key, nil
		}
	}
	if len([]byte(value)) == 32 {
		return []byte(value), nil
	}
	return nil, errors.New("CREDENTIAL_ENCRYPTION_KEY must encode exactly 32 bytes")
}

func (c *AESGCM) Encrypt(id string, kind contracts.Kind, material secret.Value) ([]byte, []byte, error) {
	if ids.Validate(id) != nil || !kind.Valid() || !material.Present() {
		return nil, nil, contracts.ErrInvalid
	}
	nonce := make([]byte, c.aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, nil, contracts.ErrInvalid
	}
	return nonce, c.aead.Seal(nil, nonce, []byte(material.Reveal()), aad(id, kind)), nil
}

func (c *AESGCM) Decrypt(record application.Record) (secret.Value, error) {
	if record.KeyVersion != 1 || len(record.Nonce) != 12 || ids.Validate(record.ID) != nil || !record.Kind.Valid() {
		return secret.Value{}, contracts.ErrInvalid
	}
	plaintext, err := c.aead.Open(nil, record.Nonce, record.Ciphertext, aad(record.ID, record.Kind))
	if err != nil || !utf8.Valid(plaintext) {
		return secret.Value{}, contracts.ErrInvalid
	}
	return secret.New(string(plaintext)), nil
}

func aad(id string, kind contracts.Kind) []byte { return []byte(id + ":" + string(kind) + ":1") }
