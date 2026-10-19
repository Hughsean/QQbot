package application

import (
	"context"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	"qqtimeagent/internal/platform/ids"
)

func (s *Service) requireAny(ctx context.Context, user, id string) (domain.Connection, error) {
	if user != "owner" || ids.Validate(id) != nil {
		return domain.Connection{}, contracts.ErrSecurity
	}
	c, err := s.dependencies.Repository.Get(ctx, id, user)
	if err != nil {
		return c, err
	}
	if c.Provider != domain.Microsoft && c.Provider != domain.QQMail {
		return domain.Connection{}, contracts.ErrInvalid
	}
	return c, nil
}

func (s *Service) EnsureAvailable(ctx context.Context, user, id string) error {
	c, err := s.requireAny(ctx, user, id)
	if err != nil {
		return err
	}
	if !available(c) {
		return contracts.ErrSecurity
	}
	return nil
}

func (s *Service) mutateSync(ctx context.Context, user, id string, update func(*domain.Connection) error) (contracts.View, error) {
	c, err := s.requireAny(ctx, user, id)
	if err != nil {
		return contracts.View{}, err
	}
	var result contracts.View
	err = s.dependencies.Guard.Run(ctx, c.Provider, func(ctx context.Context) error {
		current, err := s.require(ctx, user, id, c.Provider)
		if err != nil {
			return err
		}
		if current.Status == domain.Disconnected {
			return contracts.ErrSecurity
		}
		expected := current.Version
		if err := update(&current); err != nil {
			return err
		}
		if current.Version != expected {
			if err := s.dependencies.Repository.Save(ctx, current, expected); err != nil {
				return err
			}
		}
		result = toView(current)
		return nil
	})
	return result, err
}

func (s *Service) SyncSucceeded(ctx context.Context, user, id string, completed time.Time) (contracts.View, error) {
	if completed.IsZero() {
		return contracts.View{}, contracts.ErrInvalid
	}
	return s.mutateSync(ctx, user, id, func(c *domain.Connection) error {
		if !available(*c) {
			return contracts.ErrSecurity
		}
		c.LastSyncedAt = &completed
		c.Status, c.ReauthSince = domain.Active, nil
		c.Version++
		return nil
	})
}

func (s *Service) SyncReauthRequired(ctx context.Context, user, id string) (contracts.View, error) {
	return s.mutateSync(ctx, user, id, func(c *domain.Connection) error { return c.RequireReauthorization(s.dependencies.Clock.Now()) })
}

func (s *Service) SyncDegraded(ctx context.Context, user, id string) (contracts.View, error) {
	return s.mutateSync(ctx, user, id, func(c *domain.Connection) error { c.MarkDegraded(); return nil })
}

var _ contracts.SyncLifecycle = (*Service)(nil)
