package application

import (
	"context"
	"errors"
	"strings"
	"testing"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

func TestQQMailConnectionReauthenticationAndIsolation(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	view, err := f.q.Connect(ctx, "owner", secret.New(" 123456@QQ.COM "), secret.New("synthetic-code"))
	if err != nil {
		t.Fatal(err)
	}
	if view.Status != "ACTIVE" || view.AccountMask != "1***@qq.com" || !view.Default {
		t.Fatal("mail activation failed")
	}
	if _, err := f.q.Connect(ctx, "owner", secret.New("123456@qq.com"), secret.New("synthetic-code")); !errors.Is(err, contracts.ErrConflict) {
		t.Fatal("duplicate active mailbox accepted")
	}
	second, err := f.q.Connect(ctx, "owner", secret.New("alias@qq.com"), secret.New("synthetic-other"))
	if err != nil || second.Default {
		t.Fatal("second mailbox became default", err)
	}
	grant, err := f.q.AcquireMail(ctx, "owner", view.ID)
	if err != nil || grant.Credential.Kind() != credentials.IMAPAuthCode {
		t.Fatal("mail grant failed", err)
	}
	if material, err := grant.Credential.Reveal(f.clock.now); err != nil || material.Reveal() != "synthetic-code" {
		t.Fatal("wrong mailbox credential")
	}
	if _, err := f.q.AcquireMail(ctx, "other", view.ID); err == nil {
		t.Fatal("owner isolation bypassed")
	}
	values, err := f.q.Statuses(ctx, "owner")
	if err != nil || len(values) != 2 {
		t.Fatal("mail statuses failed")
	}
	c := f.repo.rows[view.ID]
	original := c.CredentialID
	c.RequireReauthorization(f.clock.now)
	f.repo.rows[c.ID] = c
	view, err = f.q.Connect(ctx, "owner", secret.New("123456@qq.com"), secret.New("synthetic-rotated"))
	if err != nil {
		t.Fatal(err)
	}
	if view.ID != c.ID || f.repo.rows[c.ID].CredentialID != original {
		t.Fatal("reauthorization replaced connection/reference identity")
	}
	if _, err := f.q.Disconnect(ctx, "owner", view.ID, false); err == nil {
		t.Fatal("disconnect did not require confirmation")
	}
	if _, err := f.q.Disconnect(ctx, "owner", view.ID, true); err != nil {
		t.Fatal(err)
	}
	if _, err := f.q.AcquireMail(ctx, "owner", view.ID); err == nil {
		t.Fatal("disconnected mailbox granted access")
	}
	view, err = f.q.Connect(ctx, "owner", secret.New("123456@qq.com"), secret.New("synthetic-new"))
	if err != nil || view.ID != c.ID {
		t.Fatal("explicit reauthorization failed", err)
	}
}

func TestQQMailValidationAndCompensation(t *testing.T) {
	ctx := context.Background()
	for _, address := range []string{"", "missing", "@qq.com", "name@example.test", "a@qq.com@evil.test", "x\r\n@qq.com", strings.Repeat("a", 321) + "@qq.com"} {
		f := setup(t)
		if _, err := f.q.Connect(ctx, "owner", secret.New(address), secret.New("synthetic")); err == nil {
			t.Fatal("invalid mailbox accepted")
		}
		if len(f.vault.rows) > 0 {
			t.Fatal("invalid mailbox stored credential")
		}
	}
	f := setup(t)
	if _, err := f.q.Connect(ctx, "other", secret.New("123@qq.com"), secret.New("synthetic")); err == nil {
		t.Fatal("non-owner connected mailbox")
	}
	if _, err := f.q.Connect(ctx, "owner", secret.New("123@qq.com"), secret.Value{}); err == nil {
		t.Fatal("empty authorization code accepted")
	}
	for name, inject := range map[string]func(*fixture){
		"verify": func(f *fixture) { f.verifier.err = errFailure }, "fingerprint": func(f *fixture) { f.fingerprinter.err = errFailure }, "list": func(f *fixture) { f.repo.listErr = errFailure },
		"store": func(f *fixture) { f.vault.storeErr = errFailure }, "allow": func(f *fixture) { f.effects.allowErr = errFailure }, "add": func(f *fixture) { f.repo.addErr = errFailure },
	} {
		t.Run(name, func(t *testing.T) {
			f := setup(t)
			inject(f)
			if _, err := f.q.Connect(ctx, "owner", secret.New("123@qq.com"), secret.New("synthetic")); !errors.Is(err, errFailure) {
				t.Fatal("mail failure hidden", err)
			}
			if len(f.vault.rows) > 0 {
				t.Fatal("failed activation orphaned credential")
			}
		})
	}
	f = setup(t)
	view, err := f.q.Connect(ctx, "owner", secret.New("123@qq.com"), secret.New("synthetic"))
	if err != nil {
		t.Fatal(err)
	}
	c := f.repo.rows[view.ID]
	c.Fingerprint = "legacy:old"
	c.Status = domain.ReauthRequired
	f.repo.rows[c.ID] = c
	if _, err := f.q.Connect(ctx, "owner", secret.New("123@qq.com"), secret.New("synthetic-new")); err != nil {
		t.Fatal("legacy account identity not migrated", err)
	}
	c = f.repo.rows[view.ID]
	c.SyncEnabled = false
	f.repo.rows[c.ID] = c
	if _, err := f.q.AcquireMail(ctx, "owner", view.ID); err == nil {
		t.Fatal("disabled sync granted access")
	}
	if _, err := f.q.AcquireMail(ctx, "owner", ids.New()); err == nil {
		t.Fatal("missing mailbox granted access")
	}
	c.SyncEnabled = true
	f.repo.rows[c.ID] = c
	f.vault.rows[c.CredentialID] = credentials.NewHandle(secret.New("synthetic"), credentials.RefreshToken, nil)
	if _, err := f.q.AcquireMail(ctx, "owner", view.ID); err == nil {
		t.Fatal("wrong credential kind granted")
	}
	f.vault.openErr = errFailure
	if _, err := f.q.AcquireMail(ctx, "owner", view.ID); !errors.Is(err, errFailure) {
		t.Fatal("storage failure hidden")
	}
}
