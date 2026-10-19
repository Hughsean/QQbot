package application

import (
	"context"
	"errors"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/secret"
)

const cleanupTimeout = 3 * time.Second

func (s *Service) Disconnect(ctx context.Context, user, id string, provider domain.Provider, confirmed bool) (contracts.View, error) {
	if !confirmed {
		return contracts.View{}, contracts.ErrSecurity
	}
	var result contracts.View
	err := s.dependencies.Guard.Run(ctx, provider, func(ctx context.Context) error {
		c, err := s.require(ctx, user, id, provider)
		if err != nil {
			return err
		}
		if err := s.disconnect(ctx, &c); err != nil {
			return err
		}
		result = toView(c)
		return nil
	})
	return result, err
}

func (s *Service) disconnect(ctx context.Context, c *domain.Connection) error {
	if err := s.dependencies.Sources.BlockConnection(ctx, c.ID); err != nil {
		return err
	}
	if err := s.dependencies.Jobs.CancelForConnection(ctx, c.ID, s.dependencies.Clock.Now()); err != nil {
		return err
	}
	if c.CredentialID != "" {
		if _, err := s.dependencies.Vault.Delete(ctx, credentials.Ref{ID: c.CredentialID}); err != nil {
			return err
		}
	}
	expected := c.Version
	if err := c.Disconnect(true); err != nil {
		return err
	}
	if err := s.dependencies.Repository.SaveDisconnected(ctx, *c, expected, s.dependencies.Clock.Now()); err != nil {
		return err
	}
	if err := s.dependencies.Sources.DeleteConnectionSources(ctx, c.ID); err != nil {
		return err
	}
	return s.audit(ctx, *c, "connection-disconnected")
}

// Rotation retains the existing credential reference, matching the old data
// contract and avoiding an unreachable credential after a successful update.
func (s *Service) credential(ctx context.Context, c domain.Connection, material secret.Value, kind credentials.Kind) (credentials.Ref, bool, error) {
	if c.CredentialID != "" {
		ref := credentials.Ref{ID: c.CredentialID}
		return ref, false, s.dependencies.Vault.Replace(ctx, ref, material)
	}
	ref, err := s.dependencies.Vault.Store(ctx, material, kind, nil)
	return ref, true, err
}

func (s *Service) activate(ctx context.Context, c domain.Connection, expected int, ref credentials.Ref, created bool, wasLive bool) error {
	err := s.dependencies.Sources.AllowConnection(ctx, c.ID)
	if err == nil {
		if expected == 0 {
			err = s.dependencies.Repository.Add(ctx, c)
		} else {
			err = s.dependencies.Repository.Save(ctx, c, expected)
		}
	}
	if err != nil {
		if !wasLive {
			err = errors.Join(err, s.dependencies.Sources.BlockConnection(ctx, c.ID))
		}
		if created {
			return s.erase(ctx, ref, err)
		}
		return err
	}
	return s.audit(ctx, c, "connection-activated")
}

func available(c domain.Connection) bool {
	return c.SyncEnabled && (c.Status == domain.Active || c.Status == domain.Degraded)
}
