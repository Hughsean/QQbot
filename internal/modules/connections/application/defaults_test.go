package application

import (
	"context"
	"testing"

	"qqtimeagent/internal/modules/connections/domain"
	"qqtimeagent/internal/platform/secret"
)

func TestFirstSuccessfulAccountBecomesDefaultDespitePendingOlderAuthorization(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	older, olderCallback := f.start(t, "")
	newer, newerCallback := f.start(t, "")
	f.provider.profile.AccountID = secret.New("second-account")
	second, err := f.m.Complete(ctx, newerCallback, newer.BrowserSession)
	if err != nil {
		t.Fatal(err)
	}
	if !second.Default {
		t.Fatal("abandoned older authorization prevented an active default")
	}
	f.provider.profile.AccountID = secret.New("first-account")
	first, err := f.m.Complete(ctx, olderCallback, older.BrowserSession)
	if err != nil {
		t.Fatal(err)
	}
	if first.Default || first.ID == second.ID {
		t.Fatal("out-of-order callback duplicated the default or account")
	}
	for _, status := range []domain.Status{domain.Active, domain.Degraded, domain.ReauthRequired} {
		c := f.repo.rows[second.ID]
		c.Status = status
		f.repo.rows[c.ID] = c
		if chooseDefault([]domain.Connection{c}, first.ID) {
			t.Fatal("existing live default replaced")
		}
	}
	if !chooseDefault([]domain.Connection{{ID: second.ID, Default: false, Status: domain.Active}}, first.ID) {
		t.Fatal("non-default connection reserved default slot")
	}
}
