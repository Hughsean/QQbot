package domain

import (
	"strings"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/ids"
)

type Provider string

const (
	Microsoft Provider = "MICROSOFT"
	QQMail    Provider = "QQ_MAIL"
)

type Status string

const (
	Pending        Status = "PENDING"
	Active         Status = "ACTIVE"
	Degraded       Status = "DEGRADED"
	ReauthRequired Status = "REAUTH_REQUIRED"
	Disconnected   Status = "DISCONNECTED"
)

type Connection struct {
	ID           string
	UserID       string
	Provider     Provider
	Status       Status
	AccountID    string
	AccountMask  string
	Fingerprint  string
	DisplayLabel string
	Default      bool
	SyncEnabled  bool
	Capabilities []string
	CredentialID string
	LastSyncedAt *time.Time
	ReauthEpoch  int
	ReauthSince  *time.Time
	Version      int
}

func Start(id, user string, provider Provider) (Connection, error) {
	if ids.Validate(id) != nil || user != "owner" || (provider != Microsoft && provider != QQMail) {
		return Connection{}, contracts.ErrInvalid
	}
	label := "Microsoft"
	if provider == QQMail {
		label = "Qq Mail"
	}
	return Connection{ID: id, UserID: user, Provider: provider, Status: Pending, Default: true, SyncEnabled: true, DisplayLabel: label, Version: 1}, nil
}

func (c *Connection) Activate(account, mask string, capabilities []string, credentialID string) error {
	if c.Status == Disconnected || strings.TrimSpace(account) == "" || len(capabilities) == 0 || ids.Validate(credentialID) != nil {
		return contracts.ErrInvalid
	}
	c.AccountID, c.AccountMask, c.CredentialID = account, mask, credentialID
	c.Capabilities = append([]string(nil), capabilities...)
	c.Status, c.SyncEnabled, c.ReauthSince = Active, true, nil
	c.Version++
	return nil
}

func (c *Connection) BindIdentity(fingerprint, label string, isDefault bool) error {
	if strings.TrimSpace(fingerprint) == "" || len(fingerprint) > 80 || strings.TrimSpace(label) == "" || len([]rune(label)) > 120 {
		return contracts.ErrInvalid
	}
	if c.Fingerprint != "" && !strings.HasPrefix(c.Fingerprint, "legacy:") && c.Fingerprint != fingerprint {
		return contracts.ErrConflict
	}
	c.Fingerprint, c.DisplayLabel, c.Default = strings.TrimSpace(fingerprint), strings.TrimSpace(label), isDefault
	return nil
}

func (c *Connection) RequireReauthorization(now time.Time) error {
	if now.IsZero() {
		return contracts.ErrInvalid
	}
	if c.Status == Disconnected {
		return nil
	}
	if c.Status != ReauthRequired {
		c.ReauthEpoch++
		c.ReauthSince = &now
	}
	c.Status = ReauthRequired
	c.Version++
	return nil
}

func (c *Connection) MarkDegraded() {
	if c.Status == Active || c.Status == Degraded {
		c.Status = Degraded
		c.Version++
	}
}

func (c *Connection) RestartAuthorization() error {
	if c.Status == Active {
		return contracts.ErrInvalid
	}
	c.Status, c.ReauthSince = Pending, nil
	c.Version++
	return nil
}

func (c *Connection) SetSyncEnabled(enabled bool) error {
	if c.Status == Disconnected && enabled {
		return contracts.ErrInvalid
	}
	if c.SyncEnabled != enabled {
		c.SyncEnabled = enabled
		c.Version++
	}
	return nil
}

func (c *Connection) Disconnect(credentialDeleted bool) error {
	if !credentialDeleted && c.CredentialID != "" {
		return contracts.ErrInvalid
	}
	c.CredentialID, c.Status, c.ReauthSince = "", Disconnected, nil
	c.SyncEnabled, c.Default = false, false
	c.Version++
	return nil
}
