package application

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

func TestMicrosoftAuthorizationRefreshAndDisconnect(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	start, callback := f.start(t, "")
	if _, err := f.m.Complete(ctx, callback, secret.New(strings.Repeat("x", 43))); !errors.Is(err, contracts.ErrSecurity) {
		t.Fatal("wrong browser accepted")
	}
	view, err := f.m.Complete(ctx, callback, start.BrowserSession)
	if err != nil {
		t.Fatal(err)
	}
	if view.Status != "ACTIVE" || view.Version != 2 || !view.Default || len(f.vault.rows) != 1 {
		t.Fatal("activation lost state")
	}
	serialized, _ := json.Marshal(view)
	if strings.Contains(string(serialized), "synthetic-account") || strings.Contains(string(serialized), "synthetic-refresh") || strings.Contains(string(serialized), "credential_ref") {
		t.Fatal("connection view leaked identity or credential")
	}
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); err == nil {
		t.Fatal("callback replay accepted")
	}
	grant, err := f.m.AcquireMail(ctx, "owner", view.ID)
	if err != nil || grant.ConnectionID != view.ID || grant.Credential.Kind() != credentials.AccessToken {
		t.Fatal("mail access unavailable", err)
	}
	if value, err := grant.Credential.Reveal(f.clock.now); err != nil || value.Reveal() != "synthetic-access" {
		t.Fatal("access token mismatch")
	}
	if _, err := grant.Credential.Reveal(f.provider.tokens.ExpiresAt); err == nil {
		t.Fatal("expired grant accepted")
	}
	if _, err := f.m.Refresh(ctx, "owner", view.ID); err != nil {
		t.Fatal(err)
	}
	values, err := f.m.Statuses(ctx, "owner", "MICROSOFT")
	if err != nil || len(values) != 1 {
		t.Fatal("status failed", err)
	}
	if _, err := f.m.Disconnect(ctx, "owner", view.ID, false); err == nil {
		t.Fatal("disconnect lacked confirmation")
	}
	f.effects.events = nil
	view, err = f.m.Disconnect(ctx, "owner", view.ID, true)
	if err != nil {
		t.Fatal(err)
	}
	if view.Status != "DISCONNECTED" || view.SyncEnabled || view.Default || len(f.vault.rows) != 0 {
		t.Fatal("disconnect incomplete")
	}
	if !reflect.DeepEqual(f.effects.events, []string{"block", "cancel", "credential-delete", "source-delete", "audit:connection-disconnected"}) {
		t.Fatal("cleanup order changed", f.effects.events)
	}
	if _, err := f.m.AcquireMail(ctx, "owner", view.ID); err == nil {
		t.Fatal("disconnected grant allowed")
	}
	if _, err := f.m.Refresh(ctx, "owner", view.ID); err == nil {
		t.Fatal("disconnected refresh allowed")
	}
	if _, err := f.m.Disconnect(ctx, "owner", view.ID, true); err != nil {
		t.Fatal("disconnect retry failed", err)
	}
}

func TestIncrementalAuthorizationPreservesActiveConnectionOnFailure(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	view := f.active(t)
	original := f.repo.rows[view.ID]
	for _, status := range []domain.Status{domain.Active, domain.Degraded} {
		c := f.repo.rows[view.ID]
		c.Status = status
		f.repo.rows[c.ID] = c
		start, callback := f.start(t, view.ID)
		if f.repo.rows[view.ID].Status != status || f.repo.rows[view.ID].Version != original.Version {
			t.Fatal("pending incremental authorization interrupted live service")
		}
		f.provider.completeErr = ProviderError{Class: "Authentication"}
		if _, err := f.m.Complete(ctx, callback, start.BrowserSession); err == nil {
			t.Fatal("provider failure hidden")
		}
		if f.repo.rows[view.ID].Status != status || len(f.vault.rows) != 1 {
			t.Fatal("failed incremental flow damaged current grant")
		}
	}
	f.provider.completeErr = nil
	start, callback := f.start(t, view.ID)
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); err != nil {
		t.Fatal(err)
	}
	if f.repo.rows[view.ID].CredentialID != original.CredentialID {
		t.Fatal("refresh rotation orphaned old reference")
	}
	// A late callback may not revive a connection that has been explicitly disconnected.
	start, callback = f.start(t, view.ID)
	oldCallback, oldBrowser := callback, start.BrowserSession
	if _, err := f.m.Disconnect(ctx, "owner", view.ID, true); err != nil {
		t.Fatal(err)
	}
	calls := f.provider.completes
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, contracts.ErrSecurity) {
		t.Fatal("late callback revived disconnected account")
	}
	if f.provider.completes != calls || f.repo.rows[view.ID].Status != domain.Disconnected {
		t.Fatal("late callback exchanged credentials")
	}
	start, callback = f.start(t, view.ID)
	if f.repo.rows[view.ID].Status != domain.Pending {
		t.Fatal("explicit reauthorization not restarted")
	}
	if _, err := f.m.Complete(ctx, oldCallback, oldBrowser); !errors.Is(err, contracts.ErrSecurity) {
		t.Fatal("new begin revived a pre-disconnect callback")
	}
	// The new begin cannot make an older, pre-disconnect authorization valid.
	for _, transaction := range f.repo.transactions {
		if transaction.ConnectionID == view.ID && transaction.ConsumedAt == nil && string(transaction.StateHash) != string(hash(callback.State)) {
			t.Fatal("pre-disconnect authorization remained usable")
		}
	}
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); err != nil {
		t.Fatal(err)
	}
}

func TestMicrosoftFailuresCompensateAndScopeAccounts(t *testing.T) {
	ctx := context.Background()
	for name, inject := range map[string]func(*fixture){
		"provider begin": func(f *fixture) { f.provider.beginErr = errFailure }, "vault store": func(f *fixture) { f.vault.storeErr = errFailure },
		"repository authorization": func(f *fixture) { f.repo.authErr = errFailure }, "list": func(f *fixture) { f.repo.listErr = errFailure }, "guard": func(f *fixture) { f.guard.err = errFailure },
	} {
		t.Run(name, func(t *testing.T) {
			f := setup(t)
			inject(f)
			if _, err := f.m.Begin(ctx, "owner", ""); !errors.Is(err, errFailure) {
				t.Fatal("begin failure hidden", err)
			}
			if len(f.vault.rows) != 0 || len(f.repo.rows) != 0 {
				t.Fatal("failed begin left records")
			}
		})
	}
	for name, inject := range map[string]func(*fixture){
		"open": func(f *fixture) { f.vault.openErr = errFailure }, "exchange": func(f *fixture) { f.provider.completeErr = errFailure },
		"profile": func(f *fixture) { f.provider.profileErr = errFailure }, "fingerprint": func(f *fixture) { f.fingerprinter.err = errFailure },
		"list": func(f *fixture) { f.repo.listErr = errFailure }, "credential": func(f *fixture) { f.vault.storeErr = errFailure },
		"allow": func(f *fixture) { f.effects.allowErr = errFailure }, "save": func(f *fixture) { f.repo.saveErr = errFailure },
	} {
		t.Run(name, func(t *testing.T) {
			f := setup(t)
			start, callback := f.start(t, "")
			inject(f)
			if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, errFailure) {
				t.Fatal("completion failure hidden", err)
			}
			if len(f.vault.rows) != 0 {
				t.Fatal("failed callback left credential")
			}
		})
	}
	f := setup(t)
	view := f.active(t)
	if _, err := f.m.Begin(ctx, "intruder", view.ID); !errors.Is(err, contracts.ErrSecurity) {
		t.Fatal("non-owner authorization accepted")
	}
	if _, err := f.m.Begin(ctx, "owner", ids.New()); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("missing connection accepted")
	}
	if _, err := f.m.Begin(ctx, "owner", "bad"); err == nil {
		t.Fatal("invalid ID accepted")
	}
	mail, _ := domain.Start(ids.New(), "owner", domain.QQMail)
	f.repo.rows[mail.ID] = mail
	if _, err := f.m.Begin(ctx, "owner", mail.ID); !errors.Is(err, contracts.ErrNotFound) {
		t.Fatal("provider isolation bypassed")
	}
	start, callback := f.start(t, "")
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("duplicate account connected")
	}
	if len(f.vault.rows) != 1 {
		t.Fatal("duplicate account credential persisted")
	}
	start, callback = f.start(t, view.ID)
	f.provider.profile.AccountID = secret.New("other-account")
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("existing identity replaced")
	}
	f = setup(t)
	start, callback = f.start(t, "")
	f.clock.now = f.clock.now.Add(10 * time.Minute)
	if _, err := f.m.Complete(ctx, callback, start.BrowserSession); !errors.Is(err, contracts.ErrSecurity) {
		t.Fatal("expired transaction accepted")
	}
	if _, err := f.m.Complete(ctx, contracts.Callback{}, secret.Value{}); err == nil {
		t.Fatal("missing state accepted")
	}
}

func TestRefreshErrorClassificationAndVersionFences(t *testing.T) {
	ctx := context.Background()
	for _, class := range []string{"Authentication", "TransientProvider", "RateLimit", "Permission"} {
		t.Run(class, func(t *testing.T) {
			f := setup(t)
			view := f.active(t)
			f.provider.refreshErr = ProviderError{Class: class}
			if _, err := f.m.AcquireMail(ctx, "owner", view.ID); err == nil {
				t.Fatal("provider failure hidden")
			}
			c := f.repo.rows[view.ID]
			expected := domain.Degraded
			if class == "Authentication" {
				expected = domain.ReauthRequired
			}
			if class == "Permission" {
				expected = domain.Active
			}
			if c.Status != expected {
				t.Fatal("wrong health transition", c.Status)
			}
		})
	}
	for name, inject := range map[string]func(*fixture){"open": func(f *fixture) { f.vault.openErr = errFailure }, "replace": func(f *fixture) { f.vault.replaceErr = errFailure }, "save": func(f *fixture) { f.repo.saveErr = errFailure }, "profile": func(f *fixture) { f.provider.profileErr = errFailure }, "list": func(f *fixture) { f.repo.listErr = errFailure }} {
		t.Run(name, func(t *testing.T) {
			f := setup(t)
			view := f.active(t)
			inject(f)
			if _, err := f.m.Refresh(ctx, "owner", view.ID); !errors.Is(err, errFailure) {
				t.Fatal("refresh error hidden", err)
			}
		})
	}
	f := setup(t)
	view := f.active(t)
	c := f.repo.rows[view.ID]
	c.SyncEnabled = false
	f.repo.rows[c.ID] = c
	if _, err := f.m.AcquireMail(ctx, "owner", view.ID); err == nil {
		t.Fatal("disabled sync granted access")
	}
	if _, err := f.m.AcquireMail(ctx, "other", view.ID); err == nil {
		t.Fatal("non-owner granted access")
	}
	if _, err := f.m.AcquireMail(ctx, "owner", ids.New()); err == nil {
		t.Fatal("missing connection granted access")
	}
}
