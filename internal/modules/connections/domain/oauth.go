package domain

import (
	"crypto/subtle"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
)

type OAuthTransaction struct {
	ID               string
	ConnectionID     string
	UserID           string
	StateHash        []byte
	BrowserHash      []byte
	FlowCredentialID string
	ExpiresAt        time.Time
	CreatedAt        time.Time
	ConsumedAt       *time.Time
}

func (t *OAuthTransaction) Claim(state, browser []byte, now time.Time) error {
	if now.IsZero() || t.ConsumedAt != nil || !now.Before(t.ExpiresAt) {
		return contracts.ErrSecurity
	}
	if len(state) != 32 || len(browser) != 32 {
		return contracts.ErrSecurity
	}
	if subtle.ConstantTimeCompare(t.StateHash, state) != 1 || subtle.ConstantTimeCompare(t.BrowserHash, browser) != 1 {
		return contracts.ErrSecurity
	}
	t.ConsumedAt = &now
	return nil
}
