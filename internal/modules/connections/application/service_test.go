package application

import (
	"context"
	"errors"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

func TestRequiredPortsAndStatusSecurity(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	for _, remove := range []func(*Dependencies){func(d *Dependencies) { d.Repository = nil }, func(d *Dependencies) { d.Vault = nil }, func(d *Dependencies) { d.Clock = nil }, func(d *Dependencies) { d.Fingerprinter = nil }, func(d *Dependencies) { d.Sources = nil }, func(d *Dependencies) { d.Jobs = nil }, func(d *Dependencies) { d.Guard = nil }, func(d *Dependencies) { d.Audit = nil }} {
		d := f.s.dependencies
		remove(&d)
		if _, err := New(d); err == nil {
			t.Fatal("required port missing")
		}
	}
	if _, err := NewMicrosoft(nil, f.provider); err == nil {
		t.Fatal("nil service accepted")
	}
	if _, err := NewMicrosoft(f.s, nil); err == nil {
		t.Fatal("nil provider accepted")
	}
	if _, err := NewQQMail(nil, f.verifier); err == nil {
		t.Fatal("nil service accepted")
	}
	if _, err := NewQQMail(f.s, nil); err == nil {
		t.Fatal("nil verifier accepted")
	}
	for _, input := range [][2]string{{"other", "MICROSOFT"}, {"owner", "UNKNOWN"}} {
		if _, err := f.s.Statuses(ctx, input[0], input[1]); err == nil {
			t.Fatal("status security bypassed")
		}
	}
	if _, err := f.m.Statuses(ctx, "owner", "QQ_MAIL"); err == nil {
		t.Fatal("provider status isolation bypassed")
	}
	f.repo.listErr = errFailure
	if _, err := f.q.Statuses(ctx, "owner"); !errors.Is(err, errFailure) {
		t.Fatal("list failure hidden")
	}
	if maskAccount("") != "connected account" || maskAccount("@example.test") != "connected account" || maskAccount("a@") != "connected account" || maskAccount("张三@example.test") != "张***@example.test" {
		t.Fatal("mask validation failed")
	}
}

func TestDisconnectFailuresRemainVisibleAndRetryable(t *testing.T) {
	ctx := context.Background()
	for name, inject := range map[string]func(*fixture){"block": func(f *fixture) { f.effects.blockErr = errFailure }, "cancel": func(f *fixture) { f.effects.cancelErr = errFailure }, "delete credential": func(f *fixture) { f.vault.deleteErr = errFailure }, "save": func(f *fixture) { f.repo.saveErr = errFailure }, "delete sources": func(f *fixture) { f.effects.deleteErr = errFailure }, "audit": func(f *fixture) { f.effects.auditErr = errFailure }} {
		t.Run(name, func(t *testing.T) {
			f := setup(t)
			view := f.active(t)
			inject(f)
			if _, err := f.m.Disconnect(ctx, "owner", view.ID, true); !errors.Is(err, errFailure) {
				t.Fatal("cleanup failure hidden", err)
			}
			f.effects.blockErr = nil
			f.effects.cancelErr = nil
			f.effects.deleteErr = nil
			f.effects.auditErr = nil
			f.repo.saveErr = nil
			f.vault.deleteErr = nil
			if _, err := f.m.Disconnect(ctx, "owner", view.ID, true); err != nil {
				t.Fatal("cleanup retry failed", err)
			}
		})
	}
	f := setup(t)
	view := f.active(t)
	f.repo.getErr = errFailure
	if _, err := f.m.Disconnect(ctx, "owner", view.ID, true); !errors.Is(err, errFailure) {
		t.Fatal("lookup failure hidden")
	}
}

func TestOAuthErrorAndCredentialEdges(t *testing.T) {
	ctx := context.Background()
	for name, change := range map[string]func(*fixture){
		"refresh absent": func(f *fixture) { f.provider.tokens.RefreshToken = secret.Value{} }, "scope absent": func(f *fixture) { f.provider.tokens.Capabilities = nil },
		"wrong kind": func(f *fixture) {
			for id := range f.vault.rows {
				f.vault.rows[id] = credentials.NewHandle(secret.New("synthetic"), credentials.RefreshToken, nil)
			}
		},
		"expired handle": func(f *fixture) {
			expires := f.clock.now
			for id := range f.vault.rows {
				f.vault.rows[id] = credentials.NewHandle(secret.New("synthetic"), credentials.OAuthFlow, &expires)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			f := setup(t)
			start, callback := f.start(t, "")
			change(f)
			if _, err := f.m.Complete(ctx, callback, start.BrowserSession); err == nil {
				t.Fatal("invalid authorization accepted")
			}
			if len(f.vault.rows) != 0 {
				t.Fatal("flow not erased")
			}
		})
	}
	f := setup(t)
	start, callback := f.start(t, "")
	f.vault.deleteErr = errFailure
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, errFailure) {
		t.Fatal("flow cleanup failure hidden")
	}
	f = setup(t)
	start, callback = f.start(t, "")
	f.repo.claimErr = errFailure
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, errFailure) {
		t.Fatal("claim failure hidden")
	}
	f = setup(t)
	view := f.active(t)
	start, callback = f.start(t, view.ID)
	f.vault.replaceErr = errFailure
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, errFailure) {
		t.Fatal("rotation failure hidden")
	}
	f = setup(t)
	view = f.active(t)
	start, callback = f.start(t, view.ID)
	f.repo.saveErr = errFailure
	f.effects.events = nil
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, errFailure) {
		t.Fatal("save failure hidden")
	}
	for _, event := range f.effects.events {
		if event == "block" {
			t.Fatal("failed incremental save blocked existing mailbox")
		}
	}
	if f.repo.rows[view.ID].Status != domain.Active {
		t.Fatal("incremental save damaged active state")
	}
	// Authorization can restart from pending/reauth-required without guessing the expected version.
	f = setup(t)
	c, _ := domain.Start(ids.New(), "owner", domain.Microsoft)
	f.repo.rows[c.ID] = c
	if _, err := f.m.Begin(ctx, "owner", c.ID); err != nil {
		t.Fatal("pending restart failed", err)
	}
	if f.repo.rows[c.ID].Version != 2 {
		t.Fatal("restart version not saved")
	}
}

func TestRefreshHandlesAndHealthPersistenceFailures(t *testing.T) {
	ctx := context.Background()
	f := setup(t)
	view := f.active(t)
	c := f.repo.rows[view.ID]
	f.vault.rows[c.CredentialID] = credentials.NewHandle(secret.New("synthetic"), credentials.OAuthFlow, nil)
	if _, err := f.m.Refresh(ctx, "owner", view.ID); err == nil {
		t.Fatal("wrong credential kind refreshed")
	}
	expires := f.clock.now
	f.vault.rows[c.CredentialID] = credentials.NewHandle(secret.New("synthetic"), credentials.RefreshToken, &expires)
	if _, err := f.m.Refresh(ctx, "owner", view.ID); err == nil {
		t.Fatal("expired handle refreshed")
	}
	f = setup(t)
	view = f.active(t)
	f.provider.refreshErr = errFailure
	if _, err := f.m.Refresh(ctx, "owner", view.ID); !errors.Is(err, errFailure) {
		t.Fatal("non-provider error hidden")
	}
	f.provider.refreshErr = ProviderError{Class: "Authentication"}
	f.repo.saveErr = errFailure
	if _, err := f.m.Refresh(ctx, "owner", view.ID); !errors.Is(err, errFailure) {
		t.Fatal("health persistence failure hidden")
	}
	f = setup(t)
	view = f.active(t)
	f.provider.tokens.RefreshToken = secret.Value{}
	if _, err := f.m.AcquireMail(ctx, "owner", view.ID); err != nil {
		t.Fatal("optional rotation treated as mandatory", err)
	}
	f.provider.tokens.Capabilities = []string{"User.Read"}
	if _, err := f.m.AcquireMail(ctx, "owner", view.ID); err == nil {
		t.Fatal("missing provider permission granted access")
	}
	f = setup(t)
	view = f.active(t)
	f.provider.profile.AccountID = secret.New("different")
	if _, err := f.m.Refresh(ctx, "owner", view.ID); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("refresh changed account identity")
	}
	f = setup(t)
	view = f.active(t)
	f.clock.now = time.Time{}
	f.provider.refreshErr = ProviderError{Class: "Authentication"}
	if _, err := f.m.Refresh(ctx, "owner", view.ID); err == nil {
		t.Fatal("invalid health time accepted")
	}
}
