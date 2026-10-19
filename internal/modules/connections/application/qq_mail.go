package application

import (
	"context"
	"strings"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

type QQMail struct {
	service  *Service
	verifier MailVerifier
}

func NewQQMail(service *Service, verifier MailVerifier) (*QQMail, error) {
	if service == nil || verifier == nil {
		return nil, contracts.ErrInvalid
	}
	return &QQMail{service: service, verifier: verifier}, nil
}

func (q *QQMail) Connect(ctx context.Context, user string, address, code secret.Value) (contracts.View, error) {
	canonical, err := qqAddress(address.Reveal())
	if user != "owner" || err != nil || !code.Present() {
		return contracts.View{}, contracts.ErrSecurity
	}
	var result contracts.View
	err = q.service.dependencies.Guard.Run(ctx, domain.QQMail, func(ctx context.Context) error {
		c, expected, err := q.connection(ctx, canonical)
		if err != nil {
			return err
		}
		if err := q.verifier.Verify(ctx, secret.New(canonical), code); err != nil {
			return err
		}
		wasLive := available(c)
		if err := q.activate(ctx, &c, expected, canonical, code, wasLive); err != nil {
			return err
		}
		result = toView(c)
		return nil
	})
	return result, err
}

func (q *QQMail) activate(ctx context.Context, c *domain.Connection, expected int, address string, code secret.Value, wasLive bool) error {
	if expected > 0 {
		if err := c.RestartAuthorization(); err != nil {
			return err
		}
	}
	if err := q.service.bind(ctx, c, address, address); err != nil {
		return err
	}
	ref, created, err := q.service.credential(ctx, *c, code, credentials.IMAPAuthCode)
	if err != nil {
		return err
	}
	if err := c.Activate(address, maskAccount(address), []string{"Mail.Read"}, ref.ID); err != nil {
		return err
	}
	return q.service.activate(ctx, *c, expected, ref, created, wasLive)
}

func (q *QQMail) connection(ctx context.Context, address string) (domain.Connection, int, error) {
	fingerprint, err := q.service.dependencies.Fingerprinter.Fingerprint(string(domain.QQMail), address)
	if err != nil {
		return domain.Connection{}, 0, err
	}
	values, err := q.service.dependencies.Repository.List(ctx, "owner", domain.QQMail)
	if err != nil {
		return domain.Connection{}, 0, err
	}
	for _, c := range values {
		if c.Fingerprint != fingerprint && c.AccountID != address {
			continue
		}
		if c.Status == domain.Active {
			return domain.Connection{}, 0, contracts.ErrConflict
		}
		return c, c.Version, nil
	}
	c, err := domain.Start(ids.New(), "owner", domain.QQMail)
	c.Default = !hasDefault(values)
	return c, 0, err
}

func qqAddress(value string) (string, error) {
	value = strings.ToLower(strings.TrimSpace(value))
	local, host, ok := strings.Cut(value, "@")
	if !ok || local == "" || host != "qq.com" || len(value) > 320 {
		return "", contracts.ErrInvalid
	}
	for _, r := range local {
		if !mailLocalRune(r) {
			return "", contracts.ErrInvalid
		}
	}
	return value, nil
}

func mailLocalRune(r rune) bool {
	return r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '.' || r == '_' || r == '-'
}
func secretAccount(value string) secret.Value { return secret.New(value) }

func (q *QQMail) AcquireMail(ctx context.Context, user, id string) (contracts.MailGrant, error) {
	var result contracts.MailGrant
	err := q.service.dependencies.Guard.Run(ctx, domain.QQMail, func(ctx context.Context) error {
		c, err := q.service.require(ctx, user, id, domain.QQMail)
		if err != nil {
			return err
		}
		if !available(c) {
			return contracts.ErrSecurity
		}
		handle, err := q.service.dependencies.Vault.Open(ctx, credentials.Ref{ID: c.CredentialID})
		if err != nil {
			return err
		}
		if handle.Kind() != credentials.IMAPAuthCode {
			return contracts.ErrSecurity
		}
		result = contracts.MailGrant{ConnectionID: c.ID, UserID: c.UserID, AccountID: secret.New(c.AccountID), Credential: handle}
		return nil
	})
	return result, err
}

func (q *QQMail) Disconnect(ctx context.Context, user, id string, confirmed bool) (contracts.View, error) {
	return q.service.Disconnect(ctx, user, id, domain.QQMail, confirmed)
}

func (q *QQMail) Statuses(ctx context.Context, user string) ([]contracts.View, error) {
	return q.service.Statuses(ctx, user, string(domain.QQMail))
}
