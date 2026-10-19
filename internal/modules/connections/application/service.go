package application

import (
	"context"
	"errors"
	"strconv"
	"strings"

	audit "qqtimeagent/internal/modules/audit/contracts"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/ids"
)

type Dependencies struct {
	Repository    Repository
	Vault         credentials.Vault
	Clock         clock.Clock
	Fingerprinter Fingerprinter
	Sources       contracts.SourceLifecycle
	Jobs          contracts.JobCancellation
	Guard         Guard
	Audit         audit.ConnectionAudit
}

type Service struct{ dependencies Dependencies }

func New(dependencies Dependencies) (*Service, error) {
	if !storageReady(dependencies) || !effectsReady(dependencies) {
		return nil, contracts.ErrInvalid
	}
	return &Service{dependencies: dependencies}, nil
}

func storageReady(d Dependencies) bool {
	return d.Repository != nil && d.Vault != nil && d.Clock != nil && d.Fingerprinter != nil
}
func effectsReady(d Dependencies) bool {
	return d.Sources != nil && d.Jobs != nil && d.Guard != nil && d.Audit != nil
}

func (s *Service) Statuses(ctx context.Context, user, provider string) ([]contracts.View, error) {
	if user != "owner" || (domain.Provider(provider) != domain.Microsoft && domain.Provider(provider) != domain.QQMail) {
		return nil, contracts.ErrSecurity
	}
	connections, err := s.dependencies.Repository.List(ctx, user, domain.Provider(provider))
	if err != nil {
		return nil, err
	}
	views := make([]contracts.View, 0, len(connections))
	for _, connection := range connections {
		views = append(views, toView(connection))
	}
	return views, nil
}

func toView(c domain.Connection) contracts.View {
	return contracts.View{ID: c.ID, Provider: string(c.Provider), Status: string(c.Status), Capabilities: append([]string{}, c.Capabilities...), AccountMask: c.AccountMask, LastSyncedAt: c.LastSyncedAt, DisplayLabel: c.DisplayLabel, Default: c.Default, SyncEnabled: c.SyncEnabled, Version: c.Version}
}

func (s *Service) require(ctx context.Context, user, id string, provider domain.Provider) (domain.Connection, error) {
	if user != "owner" || ids.Validate(id) != nil {
		return domain.Connection{}, contracts.ErrSecurity
	}
	c, err := s.dependencies.Repository.Get(ctx, id, user)
	if err != nil {
		return c, err
	}
	if c.Provider != provider {
		return domain.Connection{}, contracts.ErrNotFound
	}
	return c, nil
}

func (s *Service) bind(ctx context.Context, c *domain.Connection, identity, email string) error {
	fingerprint, err := s.dependencies.Fingerprinter.Fingerprint(string(c.Provider), strings.ToLower(strings.TrimSpace(identity)))
	if err != nil {
		return err
	}
	values, err := s.dependencies.Repository.List(ctx, c.UserID, c.Provider)
	if err != nil {
		return err
	}
	for _, value := range values {
		if value.ID != c.ID && value.Status != domain.Disconnected && value.Fingerprint == fingerprint {
			return contracts.ErrConflict
		}
	}
	return c.BindIdentity(fingerprint, maskAccount(email), chooseDefault(values, c.ID))
}

func chooseDefault(values []domain.Connection, id string) bool {
	for _, value := range values {
		if value.ID == id || !value.Default {
			continue
		}
		if value.Status == domain.Active || value.Status == domain.Degraded || value.Status == domain.ReauthRequired {
			return false
		}
	}
	return true
}

func hasDefault(values []domain.Connection) bool {
	for _, value := range values {
		if value.Default && value.Status != domain.Disconnected {
			return true
		}
	}
	return false
}

func maskAccount(value string) string {
	local, host, ok := strings.Cut(strings.TrimSpace(value), "@")
	if !ok || local == "" || host == "" {
		return "connected account"
	}
	runes := []rune(local)
	return string(runes[:1]) + "***@" + host
}

func (s *Service) audit(ctx context.Context, c domain.Connection, kind string) error {
	return s.dependencies.Audit.AppendConnection(ctx, audit.ConnectionEvent{ID: c.ID + ":" + strconv.Itoa(c.Version) + ":" + kind, Kind: kind, ConnectionID: c.ID, Actor: c.UserID, Provider: string(c.Provider), Status: string(c.Status), Version: c.Version, OccurredAt: s.dependencies.Clock.Now()})
}

func (s *Service) erase(ctx context.Context, ref credentials.Ref, original error) error {
	cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), cleanupTimeout)
	defer cancel()
	_, err := s.dependencies.Vault.Delete(cleanup, ref)
	return errors.Join(original, err)
}
