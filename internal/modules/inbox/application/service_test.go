package application

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/modules/inbox/domain"
)

type testClock struct{}

func (testClock) Now() time.Time { return time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC) }

type memory struct {
	item           domain.Item
	raw            contracts.RawContent
	err            error
	ingests, saves int
}

func (m *memory) Ingest(_ context.Context, e domain.Envelope, r contracts.RawContent) (contracts.IngestResult, error) {
	m.item.Envelope = e
	m.raw = r
	m.ingests++
	return contracts.IngestResult{}, m.err
}
func (m *memory) Get(context.Context, string) (domain.Item, error) { return m.item, m.err }
func (m *memory) Save(_ context.Context, i domain.Item, expected int) error {
	if i.Version != expected+1 {
		return contracts.ErrConflict
	}
	m.saves++
	m.item = i
	return m.err
}

const testID = "00000000-0000-4000-8000-000000000001"

func mail() contracts.MailChange {
	return contracts.MailChange{ExternalID: "message", Sender: contracts.Address{Address: "sender@example.test"}, Subject: "Subject", Body: "Body", ContentType: "text", OccurredAt: testClock{}.Now()}
}

func TestMailIntakePreservesProviderNeutralEnvelopeAndHashes(t *testing.T) {
	m := &memory{}
	s, err := New(m, testClock{})
	if err != nil {
		t.Fatal(err)
	}
	for _, source := range []string{"MICROSOFT_MAIL", "QQ_MAIL"} {
		for _, mime := range []string{"text", "text/plain", "html", "text/html"} {
			change := mail()
			change.ContentType = mime
			if _, err := s.IngestMail(context.Background(), testID, "owner", source, change); err != nil {
				t.Fatal(err)
			}
			e := m.item.Envelope
			if e.TrustLevel != "T2" || e.IngressType != "SYNC" || e.SourceType != source || e.ContentHash != "cd5b9d1b2e6418fb8babbdb6409b41a1c07df9d3e5c00fdb474303e3da211a9f" {
				t.Fatal("mail identity/trust/hash changed", e.ContentHash)
			}
			if mime == "text" || mime == "text/plain" {
				if m.raw.BodyText != "Body" || m.raw.BodyHTML != "" {
					t.Fatal("plain body mapping changed")
				}
			} else {
				if m.raw.BodyHTML != "Body" || m.raw.BodyText != "" {
					t.Fatal("HTML body mapping changed")
				}
			}
		}
	}
	for _, input := range []struct{ connection, user, source string }{{"invalid", "owner", "QQ_MAIL"}, {testID, "foreign", "QQ_MAIL"}, {testID, "owner", "QQ_DIRECT"}} {
		if _, err := s.IngestMail(context.Background(), input.connection, input.user, input.source, mail()); !errors.Is(err, contracts.ErrInvalid) {
			t.Fatal("invalid intake accepted")
		}
	}
	for _, mutate := range []func(*contracts.MailChange){func(c *contracts.MailChange) { c.ContentType = "application/pdf" }, func(c *contracts.MailChange) { c.Body = strings.Repeat("x", 8<<20) }, func(c *contracts.MailChange) { c.Recipients = make([]contracts.Address, 1001) }, func(c *contracts.MailChange) { c.Attachments = make([]contracts.AttachmentMetadata, 1001) }} {
		change := mail()
		mutate(&change)
		if _, err := s.IngestMail(context.Background(), testID, "owner", "QQ_MAIL", change); err == nil {
			t.Fatal("invalid body accepted")
		}
	}
	m.err = contracts.ErrStorage
	if _, err := s.IngestMail(context.Background(), testID, "owner", "QQ_MAIL", mail()); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("ingest error hidden")
	}
	if _, err := New(nil, testClock{}); err == nil {
		t.Fatal("missing repository accepted")
	}
	if _, err := New(m, nil); err == nil {
		t.Fatal("missing clock accepted")
	}
}

func TestInboxApplicationTransitionsAndFailureKeepVersions(t *testing.T) {
	m := &memory{item: domain.Item{ID: testID, Status: domain.Received, Version: 1}}
	s, _ := New(m, testClock{})
	ctx := context.Background()
	if s.MarkCompleted(ctx, testID) == nil {
		t.Fatal("invalid completion accepted")
	}
	if err := s.Fail(ctx, testID, "TransientProvider", true); err != nil {
		t.Fatal(err)
	}
	if err := s.Retry(ctx, testID); err != nil {
		t.Fatal(err)
	}
	if err := s.MarkNormalized(ctx, testID); err != nil {
		t.Fatal(err)
	}
	if s.MarkNormalized(ctx, testID) == nil {
		t.Fatal("normalized replay changed old behavior")
	}
	for _, command := range []func(context.Context, string) error{s.MarkUnderstood, s.MarkProposed, s.MarkCompleted} {
		if err := command(ctx, testID); err != nil {
			t.Fatal(err)
		}
		before := m.saves
		if err := command(ctx, testID); err != nil || m.saves != before {
			t.Fatal("idempotent transition wrote again")
		}
	}
	if s.Fail(ctx, testID, "PermanentProvider", false) == nil {
		t.Fatal("terminal failure accepted")
	}
	for _, command := range []func(context.Context, string) error{s.MarkIgnored, s.MarkNeedsReview} {
		m.item.Status = domain.Normalized
		if err := command(ctx, testID); err != nil {
			t.Fatal(err)
		}
	}
	if s.MarkNormalized(ctx, "invalid") == nil || s.Fail(ctx, "invalid", "x", true) == nil {
		t.Fatal("invalid item ID accepted")
	}
	m.err = contracts.ErrStorage
	if err := s.MarkNormalized(ctx, testID); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("load error hidden")
	}
	if err := s.Fail(ctx, testID, "x", true); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("failure load error hidden")
	}
}
