package domain

import (
	"bytes"
	"errors"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
)

const id = "00000000-0000-4000-8000-000000000001"

func TestConnectionLifecycleAndReauthEpisodes(t *testing.T) {
	c, err := Start(id, "owner", Microsoft)
	if err != nil {
		t.Fatal(err)
	}
	if c.Version != 1 || c.Status != Pending || !c.Default || !c.SyncEnabled {
		t.Fatal("invalid initial state")
	}
	if err := c.BindIdentity("v1:synthetic", "owner mailbox", true); err != nil {
		t.Fatal(err)
	}
	if err := c.Activate("synthetic-account", "a***@example.test", []string{"Mail.Read"}, id); err != nil {
		t.Fatal(err)
	}
	if err := c.RestartAuthorization(); err == nil {
		t.Fatal("active connection restarted")
	}
	c.MarkDegraded()
	c.MarkDegraded()
	if c.Status != Degraded {
		t.Fatal("health lost")
	}
	now := time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)
	if err := c.RequireReauthorization(now); err != nil {
		t.Fatal(err)
	}
	first := c.Version
	if err := c.RequireReauthorization(now.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if c.ReauthEpoch != 1 || !c.ReauthSince.Equal(now) || c.Version != first+1 {
		t.Fatal("repeated error created new episode")
	}
	if err := c.RestartAuthorization(); err != nil {
		t.Fatal(err)
	}
	if c.ReauthSince != nil || c.Status != Pending {
		t.Fatal("authorization state not reset")
	}
	before := c.Version
	c.MarkDegraded()
	if c.Version != before {
		t.Fatal("pending degraded")
	}
	if err := c.RequireReauthorization(now); err != nil {
		t.Fatal(err)
	}
	if c.ReauthEpoch != 2 {
		t.Fatal("episode not incremented")
	}
	if err := c.SetSyncEnabled(false); err != nil {
		t.Fatal(err)
	}
	before = c.Version
	if err := c.SetSyncEnabled(false); err != nil || c.Version != before {
		t.Fatal("idempotent switch changed version")
	}
	if err := c.Disconnect(false); err == nil {
		t.Fatal("credential deletion bypassed")
	}
	if err := c.Disconnect(true); err != nil {
		t.Fatal(err)
	}
	if c.Status != Disconnected || c.CredentialID != "" || c.SyncEnabled || c.Default || c.ReauthSince != nil {
		t.Fatal("disconnect failed")
	}
	before = c.Version
	c.MarkDegraded()
	if err := c.RequireReauthorization(now); err != nil || c.Version != before {
		t.Fatal("disconnected connection revived")
	}
	if err := c.SetSyncEnabled(true); err == nil {
		t.Fatal("disconnected sync enabled")
	}
	if err := c.Activate("account", "mask", []string{"Mail.Read"}, id); err == nil {
		t.Fatal("disconnected activated without explicit reauth")
	}
	if err := c.RestartAuthorization(); err != nil {
		t.Fatal(err)
	}
	if err := c.Activate("account", "mask", []string{"Mail.Read"}, id); err != nil {
		t.Fatal(err)
	}
	if c.ReauthSince != nil || !c.SyncEnabled || c.Status != Active {
		t.Fatal("activation incomplete")
	}
}

func TestIdentityAndActivationValidation(t *testing.T) {
	for _, input := range []struct {
		id, user string
		p        Provider
	}{{"bad", "owner", Microsoft}, {id, "other", Microsoft}, {id, "owner", "BAD"}} {
		if _, err := Start(input.id, input.user, input.p); err == nil {
			t.Fatal("invalid connection accepted")
		}
	}
	c, _ := Start(id, "owner", QQMail)
	if c.DisplayLabel != "Qq Mail" {
		t.Fatal("provider label lost")
	}
	for _, input := range []struct {
		a    string
		caps []string
		ref  string
	}{{"", []string{"imap"}, id}, {"account", nil, id}, {"account", []string{"imap"}, "bad"}} {
		if err := c.Activate(input.a, "mask", input.caps, input.ref); err == nil {
			t.Fatal("invalid activation accepted")
		}
	}
	for _, input := range [][2]string{{"", "label"}, {string(bytes.Repeat([]byte("x"), 81)), "label"}, {"v1:test", " "}, {"v1:test", string(bytes.Repeat([]byte("x"), 121))}} {
		if err := c.BindIdentity(input[0], input[1], false); err == nil {
			t.Fatal("invalid identity accepted")
		}
	}
	c.Fingerprint = "legacy:old"
	if err := c.BindIdentity("v1:new", "label", true); err != nil {
		t.Fatal(err)
	}
	if err := c.BindIdentity("v1:new", "new label", false); err != nil {
		t.Fatal(err)
	}
	if !errors.Is(c.BindIdentity("v1:other", "label", false), contracts.ErrConflict) {
		t.Fatal("account identity changed")
	}
	if err := c.RequireReauthorization(time.Time{}); err == nil {
		t.Fatal("zero time accepted")
	}
	c.CredentialID = ""
	if err := c.Disconnect(false); err != nil {
		t.Fatal("credential-free disconnect rejected")
	}
}

func TestOAuthClaimBrowserExpiryAndReplay(t *testing.T) {
	now := time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)
	state, browser := bytes.Repeat([]byte{1}, 32), bytes.Repeat([]byte{2}, 32)
	base := OAuthTransaction{StateHash: state, BrowserHash: browser, ExpiresAt: now.Add(time.Minute)}
	for _, input := range []struct {
		s, b []byte
		now  time.Time
	}{
		{state, browser, time.Time{}}, {state, browser, base.ExpiresAt}, {state, browser, base.ExpiresAt.Add(time.Second)},
		{nil, browser, now}, {state, nil, now}, {browser, browser, now}, {state, state, now},
	} {
		copy := base
		if !errors.Is(copy.Claim(input.s, input.b, input.now), contracts.ErrSecurity) {
			t.Fatal("invalid callback claimed")
		}
		if copy.ConsumedAt != nil {
			t.Fatal("invalid claim consumed state")
		}
	}
	if err := base.Claim(state, browser, now); err != nil {
		t.Fatal(err)
	}
	if !base.ConsumedAt.Equal(now) {
		t.Fatal("claim time lost")
	}
	if err := base.Claim(state, browser, now); err == nil {
		t.Fatal("state replay accepted")
	}
}
