// Package ids supplies UUID values without introducing Provider types into Domain.
package ids

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"strings"
)

func New() string {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		panic("cryptographic randomness unavailable")
	}
	value[6] = (value[6] & 0x0f) | 0x40
	value[8] = (value[8] & 0x3f) | 0x80
	s := hex.EncodeToString(value[:])
	return s[:8] + "-" + s[8:12] + "-" + s[12:16] + "-" + s[16:20] + "-" + s[20:]
}

func Validate(value string) error {
	if len(value) != 36 {
		return errors.New("invalid UUID")
	}
	if value[8] != '-' || value[13] != '-' || value[18] != '-' || value[23] != '-' {
		return errors.New("invalid UUID")
	}
	decoded, err := hex.DecodeString(strings.ReplaceAll(value, "-", ""))
	if err != nil || len(decoded) != 16 || value != strings.ToLower(value) {
		return errors.New("invalid UUID")
	}
	return nil
}
