package application

import (
	"context"
	"errors"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
)

func (m *Microsoft) Statuses(ctx context.Context, user, provider string) ([]contracts.View, error) {
	if provider != string(domain.Microsoft) {
		return nil, contracts.ErrInvalid
	}
	return m.service.Statuses(ctx, user, provider)
}

func (m *Microsoft) Disconnect(ctx context.Context, user, id string, confirmed bool) (contracts.View, error) {
	return m.service.Disconnect(ctx, user, id, domain.Microsoft, confirmed)
}

func (m *Microsoft) Refresh(ctx context.Context, user, id string) (contracts.View, error) {
	var result contracts.View
	err := m.service.dependencies.Guard.Run(ctx, domain.Microsoft, func(ctx context.Context) error {
		c, err := m.service.require(ctx, user, id, domain.Microsoft)
		if err != nil {
			return err
		}
		if !available(c) {
			return contracts.ErrSecurity
		}
		tokens, err := m.refresh(ctx, &c, false)
		if err != nil {
			return err
		}
		profile, err := m.provider.Profile(ctx, tokens.AccessToken)
		if err != nil {
			return err
		}
		if err := m.service.bind(ctx, &c, profile.AccountID.Reveal(), profile.Email.Reveal()); err != nil {
			return err
		}
		expected := c.Version
		if err := c.Activate(profile.AccountID.Reveal(), maskAccount(profile.Email.Reveal()), c.Capabilities, c.CredentialID); err != nil {
			return err
		}
		if err := m.service.dependencies.Repository.Save(ctx, c, expected); err != nil {
			return err
		}
		result = toView(c)
		return nil
	})
	return result, err
}

func (m *Microsoft) AcquireMail(ctx context.Context, user, id string) (contracts.MailGrant, error) {
	var result contracts.MailGrant
	err := m.service.dependencies.Guard.Run(ctx, domain.Microsoft, func(ctx context.Context) error {
		c, err := m.service.require(ctx, user, id, domain.Microsoft)
		if err != nil {
			return err
		}
		if !available(c) || !hasScope(c.Capabilities, "Mail.Read") {
			return contracts.ErrSecurity
		}
		tokens, err := m.refresh(ctx, &c, false)
		if err != nil {
			return err
		}
		if !hasScope(tokens.Capabilities, "Mail.Read") {
			return ProviderError{Class: "Permission"}
		}
		result = contracts.MailGrant{ConnectionID: c.ID, UserID: c.UserID, AccountID: secretAccount(c.AccountID), Credential: credentials.NewHandle(tokens.AccessToken, credentials.AccessToken, &tokens.ExpiresAt)}
		return nil
	})
	return result, err
}

func (m *Microsoft) refresh(ctx context.Context, c *domain.Connection, tasks bool) (Tokens, error) {
	ref := credentials.Ref{ID: c.CredentialID}
	handle, err := m.service.dependencies.Vault.Open(ctx, ref)
	if err != nil {
		return Tokens{}, err
	}
	if handle.Kind() != credentials.RefreshToken {
		return Tokens{}, contracts.ErrSecurity
	}
	material, err := handle.Reveal(m.service.dependencies.Clock.Now())
	if err != nil {
		return Tokens{}, err
	}
	tokens, err := m.provider.Refresh(ctx, material, tasks)
	if err != nil {
		return Tokens{}, m.providerFailure(ctx, c, err)
	}
	if tokens.RefreshToken.Present() {
		if err := m.service.dependencies.Vault.Replace(ctx, ref, tokens.RefreshToken); err != nil {
			return Tokens{}, err
		}
	}
	return tokens, nil
}

func (m *Microsoft) providerFailure(ctx context.Context, c *domain.Connection, err error) error {
	var provider ProviderError
	if !errors.As(err, &provider) {
		return err
	}
	expected := c.Version
	switch provider.Class {
	case "Authentication":
		if e := c.RequireReauthorization(m.service.dependencies.Clock.Now()); e != nil {
			return errors.Join(err, e)
		}
	case "TransientProvider", "RateLimit":
		c.MarkDegraded()
	default:
		return err
	}
	return errors.Join(err, m.service.dependencies.Repository.Save(ctx, *c, expected))
}

var _ contracts.Manager = (*Microsoft)(nil)
