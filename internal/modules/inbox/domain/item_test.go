package domain

import (
	"strings"
	"testing"
	"time"
)

func envelope() Envelope {
	return Envelope{ConnectionID: "00000000-0000-4000-8000-000000000001", UserID: "owner", ExternalID: "synthetic-mail", SenderID: "sender@example.test", ContentHash: strings.Repeat("a", 64), SourceType: "MICROSOFT_MAIL", IngressType: "SYNC", TrustLevel: "T2", OccurredAt: time.Date(2026, 8, 13, 0, 0, 0, 0, time.FixedZone("test", 8*3600)), ReceivedAt: time.Date(2026, 8, 13, 0, 0, 1, 0, time.UTC)}
}

func received(t *testing.T) Item {
	t.Helper()
	e := envelope()
	i, err := Receive(e.ConnectionID, "00000000-0000-4000-8000-000000000002", e)
	if err != nil {
		t.Fatal(err)
	}
	return i
}

func TestEnvelopeRequiresValidFieldsAndZonedInstants(t *testing.T) {
	if err := envelope().Validate(); err != nil {
		t.Fatal(err)
	}
	for _, mutate := range []func(*Envelope){
		func(e *Envelope) { e.ConnectionID = "invalid" }, func(e *Envelope) { e.UserID = " " },
		func(e *Envelope) { e.ExternalID = "" }, func(e *Envelope) { e.SenderID = "" },
		func(e *Envelope) { e.OccurredAt = time.Time{} }, func(e *Envelope) { e.ReceivedAt = time.Time{} },
		func(e *Envelope) { e.ContentHash = "invalid" }, func(e *Envelope) { e.ContentHash = "ab" },
		func(e *Envelope) { e.DedupeKey = strings.Repeat("x", 513) }, func(e *Envelope) { e.ThreadID = "a\x00b" },
		func(e *Envelope) { e.SenderDisplay = string([]byte{0xff}) }, func(e *Envelope) { e.SourceType = "untrusted" },
		func(e *Envelope) { e.TrustLevel = "T1" },
	} {
		e := envelope()
		mutate(&e)
		if e.Validate() == nil {
			t.Fatal("invalid envelope accepted")
		}
		if _, err := Receive(e.ConnectionID, "00000000-0000-4000-8000-000000000002", e); err == nil {
			t.Fatal("receive skipped envelope validation")
		}
	}
	if _, err := Receive("invalid", "invalid", envelope()); err == nil {
		t.Fatal("invalid item IDs accepted")
	}
	if _, err := Receive(envelope().ConnectionID, "invalid", envelope()); err == nil {
		t.Fatal("invalid raw ID accepted")
	}
}

func TestSourceTrustCannotBePromotedByExternalContent(t *testing.T) {
	for _, source := range []struct{ kind, ingress, trust string }{
		{"MICROSOFT_MAIL", "SYNC", "T2"}, {"QQ_MAIL", "SYNC", "T2"},
		{"QQ_FORWARD", "FORWARDED", "T2"}, {"OWNER_NOTE", "DIRECT", "T2"}, {"QQ_DIRECT", "DIRECT", "T1"},
	} {
		e := envelope()
		e.SourceType, e.IngressType, e.TrustLevel = source.kind, source.ingress, source.trust
		if e.Validate() != nil {
			t.Fatalf("source %s rejected", source.kind)
		}
		e.TrustLevel = "T3"
		if e.Validate() == nil {
			t.Fatal("invalid trust level accepted")
		}
		e.TrustLevel = source.trust
		e.IngressType = "WEBHOOK"
		if e.Validate() == nil {
			t.Fatal("invalid ingress accepted")
		}
	}
}

func TestInboxRetryNormalizeComplete(t *testing.T) {
	i := received(t)
	if err := i.Fail("TransientProvider", true); err != nil {
		t.Fatal(err)
	}
	if i.Status != FailedRetryable || i.RetryCount != 1 || i.Version != 2 {
		t.Fatal("retry state lost")
	}
	for _, target := range []Status{Received, Normalized, Understood, Proposed, Completed} {
		previous := i.Version
		if err := i.Transition(target); err != nil || i.Version != previous+1 || i.FailureClass != "" {
			t.Fatal("transition/version/clearing failed", err)
		}
	}
	if i.Fail("PermanentProvider", false) == nil {
		t.Fatal("terminal item failed")
	}
}

func TestInboxAllTransitionsAndTerminalFailureBranches(t *testing.T) {
	states := []Status{Received, Normalized, Understood, Proposed, Completed, Ignored, NeedsReview, FailedRetryable, FailedFinal}
	want := map[Status][]Status{Received: {Normalized}, Normalized: {Understood, Completed, Ignored, NeedsReview}, Understood: {Proposed, Completed}, Proposed: {Completed}, FailedRetryable: {Received, Normalized}}
	for _, from := range states {
		for _, to := range append(states, Status("UNKNOWN")) {
			i := received(t)
			i.Status = from
			allowed := false
			for _, target := range want[from] {
				allowed = allowed || target == to
			}
			if err := i.Transition(to); (err == nil) != allowed {
				t.Fatalf("unexpected transition %s -> %s", from, to)
			}
		}
		for _, retry := range []bool{false, true} {
			i := received(t)
			i.Status = from
			terminal := from == Completed || from == Ignored || from == FailedFinal
			if err := i.Fail("PermanentProvider", retry); (err != nil) != terminal {
				t.Fatal("terminal failure rule changed")
			}
		}
	}
	for _, class := range []string{" ", strings.Repeat("x", 81), "a\x00b"} {
		i := received(t)
		if i.Fail(class, true) == nil || i.Version != 1 {
			t.Fatal("invalid failure mutated item")
		}
	}
}
