package contracts

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/secret"
)

var (
	ErrInvalid  = errors.New("invalid connection request")
	ErrNotFound = errors.New("connection does not exist")
	ErrConflict = errors.New("connection identity or version conflict")
	ErrSecurity = errors.New("connection security policy rejected request")
	ErrStorage  = errors.New("connection persistence failed")
)

type View struct {
	ID           string     `json:"connection_id"`
	Provider     string     `json:"provider"`
	Status       string     `json:"status"`
	Capabilities []string   `json:"capabilities"`
	AccountMask  string     `json:"account_mask"`
	LastSyncedAt *time.Time `json:"last_synced_at"`
	DisplayLabel string     `json:"display_label"`
	Default      bool       `json:"is_default"`
	SyncEnabled  bool       `json:"sync_enabled"`
	Version      int        `json:"version"`
}

func (v View) MarshalJSON() ([]byte, error) {
	type wire View
	value := wire(v)
	value.Capabilities = append([]string{}, v.Capabilities...)
	var mask *string
	if v.AccountMask != "" {
		mask = &v.AccountMask
	}
	return json.Marshal(struct {
		wire
		Mask *string `json:"account_mask"`
	}{wire: value, Mask: mask})
}

type Authorization struct {
	URL            secret.Value
	BrowserSession secret.Value
}

type Callback struct {
	State     secret.Value
	Code      secret.Value
	ErrorCode string
}

type Manager interface {
	Begin(context.Context, string, string) (Authorization, error)
	Complete(context.Context, Callback, secret.Value) (View, error)
	Statuses(context.Context, string, string) ([]View, error)
	Disconnect(context.Context, string, string, bool) (View, error)
}

type QQMailManager interface {
	Connect(context.Context, string, secret.Value, secret.Value) (View, error)
	Statuses(context.Context, string) ([]View, error)
	Disconnect(context.Context, string, string, bool) (View, error)
}

type ProviderError struct{ Class string }

func (e ProviderError) Error() string { return "connection provider failure: " + e.Class }

type MailGrant struct {
	ConnectionID string
	UserID       string
	AccountID    secret.Value
	Credential   credentials.Handle
}

type SourceLifecycle interface {
	AllowConnection(context.Context, string) error
	BlockConnection(context.Context, string) error
	DeleteConnectionSources(context.Context, string) error
}

type JobCancellation interface {
	CancelForConnection(context.Context, string, time.Time) error
}

type SyncLifecycle interface {
	EnsureAvailable(context.Context, string, string) error
	SyncSucceeded(context.Context, string, string, time.Time) (View, error)
	SyncReauthRequired(context.Context, string, string) (View, error)
	SyncDegraded(context.Context, string, string) (View, error)
}

type MailAccess interface {
	AcquireMail(context.Context, string, string) (MailGrant, error)
}
