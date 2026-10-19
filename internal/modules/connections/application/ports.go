package application

import (
	"context"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	"qqtimeagent/internal/platform/secret"
)

type Repository interface {
	Add(context.Context, domain.Connection) error
	Get(context.Context, string, string) (domain.Connection, error)
	List(context.Context, string, domain.Provider) ([]domain.Connection, error)
	Save(context.Context, domain.Connection, int) error
	SaveDisconnected(context.Context, domain.Connection, int, time.Time) error
	AddAuthorization(context.Context, domain.Connection, int, domain.OAuthTransaction) error
	ClaimTransaction(context.Context, []byte, []byte, time.Time) (domain.OAuthTransaction, error)
}

type Tokens struct {
	AccessToken  secret.Value
	RefreshToken secret.Value
	ExpiresAt    time.Time
	Capabilities []string
}

type Profile struct {
	AccountID secret.Value
	Email     secret.Value
}

type ProviderAuthorization struct {
	URL  secret.Value
	Flow secret.Value
}

type MicrosoftProvider interface {
	Begin(context.Context, secret.Value) (ProviderAuthorization, error)
	Complete(context.Context, secret.Value, contracts.Callback) (Tokens, error)
	Refresh(context.Context, secret.Value, bool) (Tokens, error)
	Profile(context.Context, secret.Value) (Profile, error)
}

type Fingerprinter interface {
	Fingerprint(string, string) (string, error)
}

// Guard serializes a provider's owner mutations, including credential rotation
// and disconnect. Its lock never spans a shared transaction across modules.
type Guard interface {
	Run(context.Context, domain.Provider, func(context.Context) error) error
}

type MailVerifier interface {
	Verify(context.Context, secret.Value, secret.Value) error
}

// ProviderError exposes a classification, never the upstream response.
type ProviderError = contracts.ProviderError
