package application_test

import (
	"context"
	"testing"
	"time"

	"qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/secret"
)

func TestLongLivedRecordProducesBoundedHandleWithoutChangingStorageExpiry(t *testing.T) {
	v, m, c := fixture(t)
	ctx := context.Background()
	ref, err := v.Store(ctx, secret.New("synthetic"), contracts.RefreshToken, nil)
	if err != nil {
		t.Fatal(err)
	}
	h, err := v.Open(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	c.now = c.now.Add(time.Minute)
	if _, err := h.Reveal(c.now); err == nil {
		t.Fatal("long-lived credential handle remained usable")
	}
	if m.rows[ref.ID].ExpiresAt != nil {
		t.Fatal("handle TTL changed persistent expiry")
	}
	if current, err := v.Open(ctx, ref); err != nil {
		t.Fatal(err)
	} else if _, err := current.Reveal(c.now); err != nil {
		t.Fatal("fresh handle not available")
	}
	c.now = time.Time{}
	if _, err := v.Open(ctx, ref); err == nil {
		t.Fatal("zero clock opened credential")
	}
	if err := v.Replace(ctx, ref, secret.New("synthetic-next")); err == nil {
		t.Fatal("zero clock replaced credential")
	}
}
