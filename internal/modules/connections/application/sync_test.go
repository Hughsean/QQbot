package application

import (
	"context"
	"errors"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

func TestSyncLifecycleRestoresHealthAndFencesDisconnectedAccounts(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	ms := f.active(t)
	mail, err := f.q.Connect(ctx, "owner", secret.New("123@qq.com"), secret.New("synthetic"))
	if err != nil {
		t.Fatal(err)
	}
	for _, view := range []contracts.View{ms, mail} {
		if err := f.s.EnsureAvailable(ctx, "owner", view.ID); err != nil {
			t.Fatal(err)
		}
		if updated, err := f.s.SyncDegraded(ctx, "owner", view.ID); err != nil || updated.Status != "DEGRADED" {
			t.Fatal("degrade failed", err)
		}
		completed := f.clock.now.Add(time.Minute)
		if updated, err := f.s.SyncSucceeded(ctx, "owner", view.ID, completed); err != nil || updated.Status != "ACTIVE" || !updated.LastSyncedAt.Equal(completed) {
			t.Fatal("sync completion lost timestamp/health", err)
		}
		if updated, err := f.s.SyncReauthRequired(ctx, "owner", view.ID); err != nil || updated.Status != "REAUTH_REQUIRED" {
			t.Fatal("reauth required failed", err)
		}
		episode := f.repo.rows[view.ID].ReauthEpoch
		if _, err := f.s.SyncReauthRequired(ctx, "owner", view.ID); err != nil || f.repo.rows[view.ID].ReauthEpoch != episode {
			t.Fatal("repeated reauth error made a new episode")
		}
		if _, err := f.s.SyncSucceeded(ctx, "owner", view.ID, completed); err == nil {
			t.Fatal("sync completion bypassed reauthorization")
		}
		if _, err := f.s.SyncDegraded(ctx, "owner", view.ID); err != nil {
			t.Fatal("neutral health retry failed", err)
		}
		if err := f.s.EnsureAvailable(ctx, "owner", view.ID); err == nil {
			t.Fatal("unavailable connection synchronized")
		}
		if _, err := f.s.Disconnect(ctx, "owner", view.ID, domain.Provider(view.Provider), true); err != nil {
			t.Fatal(err)
		}
		if _, err := f.s.SyncReauthRequired(ctx, "owner", view.ID); err == nil {
			t.Fatal("disconnected connection marked reauth")
		}
	}
	if _, err := f.s.SyncSucceeded(ctx, "owner", ms.ID, time.Time{}); err == nil {
		t.Fatal("zero completion time accepted")
	}
	if err := f.s.EnsureAvailable(ctx, "other", ms.ID); err == nil {
		t.Fatal("non-owner sync allowed")
	}
	if err := f.s.EnsureAvailable(ctx, "owner", "bad"); err == nil {
		t.Fatal("invalid sync ID accepted")
	}
	if _, err := f.s.SyncDegraded(ctx, "owner", ids.New()); err == nil {
		t.Fatal("missing connection changed")
	}
	c, _ := domain.Start(ids.New(), "owner", domain.QQMail)
	c.Provider = "UNKNOWN"
	f.repo.rows[c.ID] = c
	if err := f.s.EnsureAvailable(ctx, "owner", c.ID); err == nil {
		t.Fatal("unknown provider synchronized")
	}
	f = setup(t)
	ms = f.active(t)
	f.repo.saveErr = errFailure
	if _, err := f.s.SyncDegraded(ctx, "owner", ms.ID); !errors.Is(err, errFailure) {
		t.Fatal("sync persistence error hidden")
	}
	f.repo.saveErr = nil
	f.clock.now = time.Time{}
	if _, err := f.s.SyncReauthRequired(ctx, "owner", ms.ID); err == nil {
		t.Fatal("zero reauth time accepted")
	}
}
