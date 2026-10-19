package application

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

type Microsoft struct {
	service  *Service
	provider MicrosoftProvider
}

func NewMicrosoft(service *Service, provider MicrosoftProvider) (*Microsoft, error) {
	if service == nil || provider == nil {
		return nil, contracts.ErrInvalid
	}
	return &Microsoft{service: service, provider: provider}, nil
}

func tokenSecret() secret.Value {
	value := make([]byte, 32)
	if _, err := rand.Read(value); err != nil {
		panic("secure random source unavailable")
	}
	return secret.New(base64.RawURLEncoding.EncodeToString(value))
}
func hash(value secret.Value) []byte {
	digest := sha256.Sum256([]byte(value.Reveal()))
	return digest[:]
}

func (m *Microsoft) Begin(ctx context.Context, user, id string) (contracts.Authorization, error) {
	if user != "owner" {
		return contracts.Authorization{}, contracts.ErrSecurity
	}
	var result contracts.Authorization
	err := m.service.dependencies.Guard.Run(ctx, domain.Microsoft, func(ctx context.Context) error {
		c, expected, err := m.authorizationConnection(ctx, user, id)
		if err != nil {
			return err
		}
		state, browser := tokenSecret(), tokenSecret()
		start, err := m.provider.Begin(ctx, state)
		if err != nil {
			return err
		}
		now := m.service.dependencies.Clock.Now()
		expires := now.Add(10 * time.Minute)
		ref, err := m.service.dependencies.Vault.Store(ctx, start.Flow, credentials.OAuthFlow, &expires)
		if err != nil {
			return err
		}
		t := domain.OAuthTransaction{ID: ids.New(), ConnectionID: c.ID, UserID: user, StateHash: hash(state), BrowserHash: hash(browser), FlowCredentialID: ref.ID, CreatedAt: now, ExpiresAt: expires}
		if err := m.service.dependencies.Repository.AddAuthorization(ctx, c, expected, t); err != nil {
			return m.service.erase(ctx, ref, err)
		}
		result = contracts.Authorization{URL: start.URL, BrowserSession: browser}
		return nil
	})
	return result, err
}

func (m *Microsoft) authorizationConnection(ctx context.Context, user, id string) (domain.Connection, int, error) {
	if id == "" {
		c, err := domain.Start(ids.New(), user, domain.Microsoft)
		if err != nil {
			return c, 0, err
		}
		values, err := m.service.dependencies.Repository.List(ctx, user, domain.Microsoft)
		c.Default = !hasDefault(values)
		return c, 0, err
	}
	c, err := m.service.require(ctx, user, id, domain.Microsoft)
	if err != nil {
		return c, 0, err
	}
	expected := c.Version
	if c.Status != domain.Active && c.Status != domain.Degraded {
		err = c.RestartAuthorization()
	}
	return c, expected, err
}

func (m *Microsoft) Complete(ctx context.Context, callback contracts.Callback, browser secret.Value) (result contracts.View, err error) {
	if !validCallback(callback, browser) {
		return result, contracts.ErrSecurity
	}
	var ref credentials.Ref
	defer func() {
		if ref.ID != "" {
			err = m.service.erase(ctx, ref, err)
		}
	}()
	err = m.service.dependencies.Guard.Run(ctx, domain.Microsoft, func(ctx context.Context) error {
		t, e := m.service.dependencies.Repository.ClaimTransaction(ctx, hash(callback.State), hash(browser), m.service.dependencies.Clock.Now())
		if e != nil {
			return e
		}
		ref = credentials.Ref{ID: t.FlowCredentialID}
		c, e := m.service.require(ctx, t.UserID, t.ConnectionID, domain.Microsoft)
		if e != nil {
			return e
		}
		if c.Status == domain.Disconnected {
			return contracts.ErrSecurity
		}
		if e = m.complete(ctx, &c, ref, callback); e != nil {
			return e
		}
		result = toView(c)
		return nil
	})
	return result, err
}

func validCallback(callback contracts.Callback, browser secret.Value) bool {
	return len(callback.State.Reveal()) >= 32 && len(callback.State.Reveal()) <= 256 && len(browser.Reveal()) >= 32 && len(browser.Reveal()) <= 256
}

func (m *Microsoft) complete(ctx context.Context, c *domain.Connection, ref credentials.Ref, callback contracts.Callback) error {
	tokens, err := m.authorizationTokens(ctx, ref, callback)
	if err != nil {
		return err
	}
	profile, err := m.provider.Profile(ctx, tokens.AccessToken)
	if err != nil {
		return err
	}
	return m.activate(ctx, c, tokens, profile)
}

func (m *Microsoft) authorizationTokens(ctx context.Context, ref credentials.Ref, callback contracts.Callback) (Tokens, error) {
	flow, err := m.service.dependencies.Vault.Open(ctx, ref)
	if err != nil {
		return Tokens{}, err
	}
	if flow.Kind() != credentials.OAuthFlow {
		return Tokens{}, contracts.ErrSecurity
	}
	material, err := flow.Reveal(m.service.dependencies.Clock.Now())
	if err != nil {
		return Tokens{}, err
	}
	tokens, err := m.provider.Complete(ctx, material, callback)
	if err != nil {
		return Tokens{}, err
	}
	if !tokens.RefreshToken.Present() || !hasScope(tokens.Capabilities, "Mail.Read") {
		return Tokens{}, ProviderError{Class: "Authentication"}
	}
	return tokens, nil
}

func (m *Microsoft) activate(ctx context.Context, c *domain.Connection, tokens Tokens, profile Profile) error {
	expected, wasLive := c.Version, available(*c)
	if err := m.service.bind(ctx, c, profile.AccountID.Reveal(), profile.Email.Reveal()); err != nil {
		return err
	}
	refresh, created, err := m.service.credential(ctx, *c, tokens.RefreshToken, credentials.RefreshToken)
	if err != nil {
		return err
	}
	if err := c.Activate(profile.AccountID.Reveal(), maskAccount(profile.Email.Reveal()), tokens.Capabilities, refresh.ID); err != nil {
		return err
	}
	return m.service.activate(ctx, *c, expected, refresh, created, wasLive)
}

func hasScope(values []string, scope string) bool {
	for _, value := range values {
		if value == scope {
			return true
		}
	}
	return false
}
