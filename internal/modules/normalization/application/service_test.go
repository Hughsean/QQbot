package application

import (
	"context"
	"errors"
	"strings"
	"testing"

	"qqtimeagent/internal/modules/normalization/contracts"
)

type memory struct {
	value contracts.Content
	calls int
	err   error
}

func (m *memory) Upsert(_ context.Context, v contracts.Content) error {
	m.calls++
	m.value = v
	return m.err
}
func (m *memory) Get(context.Context, string) (contracts.Content, error) { return m.value, m.err }

type htmlText struct {
	value  string
	err    error
	cancel context.CancelFunc
}

func (h htmlText) Extract(context.Context, string) (string, error) {
	if h.cancel != nil {
		h.cancel()
	}
	return h.value, h.err
}
func input() contracts.Input {
	return contracts.Input{InboxItemID: "00000000-0000-4000-8000-000000000001", Subject: " Subject ", BodyText: " Body ", BodyHTML: "<p>ignored</p>", SourceHash: strings.Repeat("a", 64), SourceRef: "mail:synthetic"}
}

func TestNormalizationDeterministicPrefersTextAndRequiresHash(t *testing.T) {
	repo := &memory{}
	s, err := New(repo, htmlText{err: errors.New("HTML must not be called")})
	if err != nil {
		t.Fatal(err)
	}
	first, err := s.Normalize(context.Background(), input())
	if err != nil {
		t.Fatal(err)
	}
	second, err := s.Normalize(context.Background(), input())
	if err != nil || first != second || first.Subject != "Subject" || first.Body != "Body" || first.NormalizerVersion != "mail-text-v1" {
		t.Fatal("normalization changed", err)
	}
	if got, err := s.Get(context.Background(), first.InboxItemID); err != nil || got != first {
		t.Fatal("query changed result")
	}
	if _, err := s.Get(context.Background(), "invalid"); !errors.Is(err, contracts.ErrInvalid) {
		t.Fatal("invalid query ID accepted")
	}
	for _, mutate := range []func(*contracts.Input){
		func(i *contracts.Input) { i.SourceHash = " " }, func(i *contracts.Input) { i.SourceHash = "ab" },
		func(i *contracts.Input) { i.InboxItemID = "invalid" }, func(i *contracts.Input) { i.SourceRef = strings.Repeat("x", 513) },
		func(i *contracts.Input) { i.Subject = "a\x00b" }, func(i *contracts.Input) { i.BodyText = string([]byte{0xff}) },
	} {
		i := input()
		mutate(&i)
		if _, err := s.Normalize(context.Background(), i); !errors.Is(err, contracts.ErrInvalid) {
			t.Fatal("invalid input accepted")
		}
	}
	i := input()
	i.BodyText = strings.Repeat("x", MaxInputBytes)
	if _, err := s.Normalize(context.Background(), i); !errors.Is(err, contracts.ErrResourceLimit) {
		t.Fatal("oversize input accepted")
	}
	if repo.calls != 2 {
		t.Fatal("invalid input reached persistence")
	}
}

func TestHTMLFallbackFailureAndCancellationNeverPersistPartialResult(t *testing.T) {
	repo := &memory{}
	s, _ := New(repo, htmlText{value: " HTML body "})
	i := input()
	i.BodyText = " \t"
	if v, err := s.Normalize(context.Background(), i); err != nil || v.Body != "HTML body" {
		t.Fatal("HTML fallback failed")
	}
	repo.calls = 0
	s, _ = New(repo, htmlText{err: contracts.ErrResourceLimit})
	if _, err := s.Normalize(context.Background(), i); !errors.Is(err, contracts.ErrResourceLimit) || repo.calls != 0 {
		t.Fatal("parser failure persisted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := s.Normalize(ctx, input()); !errors.Is(err, context.Canceled) {
		t.Fatal("cancellation ignored")
	}
	ctx, cancel = context.WithCancel(context.Background())
	defer cancel()
	s, _ = New(repo, htmlText{value: "partial", cancel: cancel})
	if _, err := s.Normalize(ctx, i); !errors.Is(err, context.Canceled) || repo.calls != 0 {
		t.Fatal("cancelled parse persisted")
	}
	repo.err = contracts.ErrStorage
	s, _ = New(repo, htmlText{})
	if _, err := s.Normalize(context.Background(), input()); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("persistence error hidden")
	}
	if _, err := s.Get(context.Background(), input().InboxItemID); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("query error hidden")
	}
	if _, err := New(nil, htmlText{}); err == nil {
		t.Fatal("missing repository accepted")
	}
	if _, err := New(repo, nil); err == nil {
		t.Fatal("missing parser accepted")
	}
}
