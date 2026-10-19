//go:build integration

package goaccounts

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	connectionDomain "qqtimeagent/internal/modules/connections/domain"
	connections "qqtimeagent/internal/modules/connections/infrastructure"
	"qqtimeagent/internal/modules/identity/application"
	"qqtimeagent/internal/modules/identity/contracts"
	"qqtimeagent/internal/modules/identity/infrastructure"
	"qqtimeagent/internal/platform/ids"
)

func defaultPreferences() contracts.Preferences {
	return contracts.Preferences{UserID: "owner", Timezone: "Asia/Shanghai", WorkStart: 9 * 3600e6, WorkEnd: 18 * 3600e6, LunchStart: 12 * 3600e6, LunchEnd: 13 * 3600e6, WorkingWeekdays: []int32{0, 1, 2, 3, 4}, DefaultEventMinutes: 60, DefaultTaskMinutes: 30, DigestLocalTime: 8 * 3600e6, QuietHoursEnabled: true, QuietStart: 22 * 3600e6, QuietEnd: 7 * 3600e6}
}

func TestIdentityPersistenceConcurrentDefaultsAndUnicodeRules(t *testing.T) {
	pool := database(t)
	repo := infrastructure.Repository{Pool: pool}
	ctx := context.Background()
	now := time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)
	p := defaultPreferences()
	p.WorkStart++ // Preserve sub-second precision from old TIME columns.
	s, err := application.New(repo, p, fixedClock{now})
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for range 12 {
		wg.Go(func() {
			value, err := s.Preferences(ctx, "owner")
			if err != nil || value.WorkStart != p.WorkStart {
				t.Error("default initialization lost precision", err)
			}
		})
	}
	wg.Wait()
	other := p
	other.DefaultTaskMinutes = 90
	if value, err := repo.Initialize(ctx, other); err != nil || value.DefaultTaskMinutes != 30 {
		t.Fatal("defaults overwritten existing preferences", err)
	}
	first, err := s.RegisterAlias(ctx, "owner", "Straẞe Owner")
	if err != nil {
		t.Fatal(err)
	}
	second, err := s.RegisterAlias(ctx, "owner", " strasse\towner ")
	if err != nil || second != first {
		t.Fatal("Unicode alias idempotency failed", err)
	}
	if values, err := s.Aliases(ctx, "owner"); err != nil || len(values) != 1 {
		t.Fatal("alias persistence failed", err)
	}
	if values, err := repo.Aliases(ctx, "other"); err != nil || len(values) != 0 {
		t.Fatal("owner aliases leaked")
	}
	rule, err := s.RegisterMailRule(ctx, "owner", contracts.Subject, " Exam  Week ", contracts.Notify)
	if err != nil {
		t.Fatal(err)
	}
	updated, err := s.RegisterMailRule(ctx, "owner", contracts.Subject, "exam week", contracts.Hold)
	if err != nil || rule.ID != updated.ID || updated.Action != contracts.Hold {
		t.Fatal("mail rule update failed", err)
	}
	if values, err := s.MailRules(ctx, "owner"); err != nil || len(values) != 1 {
		t.Fatal("rules persistence failed", err)
	}
	if values, err := repo.MailRules(ctx, "other"); err != nil || len(values) != 0 {
		t.Fatal("mail rules leaked")
	}
	if _, err := repo.Preferences(ctx, "other"); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("missing preferences not classified")
	}
	pool.Close()
	if _, err := repo.Preferences(ctx, "owner"); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if _, err := repo.Initialize(ctx, p); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if _, err := repo.Aliases(ctx, "owner"); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if _, err := repo.AddAlias(ctx, "owner", first, "normalized", now); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if _, err := repo.MailRules(ctx, "owner"); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
	if _, err := repo.PutMailRule(ctx, "owner", rule, "normalized", now); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("storage error hidden")
	}
}

func TestGuardSerializesWithoutExhaustingRepositoryPool(t *testing.T) {
	pool := database(t)
	config := pool.Config()
	config.MaxConns = 1
	small, err := pgxpool.NewWithConfig(context.Background(), config)
	if err != nil {
		t.Fatal(err)
	}
	defer small.Close()
	guard := connections.NewGuard(small)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	c, _ := connectionDomain.Start(ids.New(), "owner", connectionDomain.Microsoft)
	repo := connections.Repository{Pool: small}
	if err := repo.Add(ctx, c); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for range 12 {
		wg.Go(func() {
			if err := guard.Run(ctx, connectionDomain.Microsoft, func(ctx context.Context) error {
				c, err := repo.Get(ctx, c.ID, "owner")
				if err != nil {
					return err
				}
				expected := c.Version
				c.Version++
				return repo.Save(ctx, c, expected)
			}); err != nil {
				t.Error("guard failed or repository pool deadlocked", err)
			}
		})
	}
	wg.Wait()
	stored, err := repo.Get(ctx, c.ID, "owner")
	if err != nil || stored.Version != 13 {
		t.Fatal("guard lost concurrent mutations", err)
	}
	if err := guard.Run(ctx, "UNKNOWN", func(context.Context) error { t.Fatal("invalid provider invoked work"); return nil }); err == nil {
		t.Fatal("invalid provider guard accepted")
	}
	canceled, stop := context.WithCancel(ctx)
	stop()
	if err := guard.Run(canceled, connectionDomain.Microsoft, func(context.Context) error { t.Fatal("canceled guard invoked work"); return nil }); err == nil {
		t.Fatal("canceled guard accepted")
	}
	if err := guard.Run(ctx, connectionDomain.QQMail, func(context.Context) error { return contracts.ErrInvalid }); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("guard hid work error")
	}
}
