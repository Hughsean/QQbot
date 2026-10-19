package application

import (
	"context"
	"encoding/base64"
	"errors"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/identity/contracts"
	"qqtimeagent/internal/modules/identity/domain"
	"qqtimeagent/internal/platform/secret"
)

type fixedClock struct{ now time.Time }

func (c *fixedClock) Now() time.Time { return c.now }

type memory struct {
	preferences     contracts.Preferences
	getErr, initErr error
	aliases         map[string]contracts.Alias
	rules           map[string]contracts.MailRule
}

func (m *memory) Preferences(context.Context, string) (contracts.Preferences, error) {
	return m.preferences, m.getErr
}
func (m *memory) Initialize(_ context.Context, p contracts.Preferences) (contracts.Preferences, error) {
	if m.initErr != nil {
		return p, m.initErr
	}
	m.preferences = p
	m.getErr = nil
	return p, nil
}
func (m *memory) Aliases(context.Context, string) ([]contracts.Alias, error) {
	result := []contracts.Alias{}
	for _, a := range m.aliases {
		result = append(result, a)
	}
	return result, nil
}
func (m *memory) AddAlias(_ context.Context, _ string, a contracts.Alias, normalized string, _ time.Time) (contracts.Alias, error) {
	if previous, ok := m.aliases[normalized]; ok {
		return previous, nil
	}
	m.aliases[normalized] = a
	return a, nil
}
func (m *memory) MailRules(context.Context, string) ([]contracts.MailRule, error) {
	result := []contracts.MailRule{}
	for _, a := range m.rules {
		result = append(result, a)
	}
	return result, nil
}
func (m *memory) PutMailRule(_ context.Context, _ string, r contracts.MailRule, normalized string, _ time.Time) (contracts.MailRule, error) {
	key := string(r.Field) + normalized
	if previous, ok := m.rules[key]; ok {
		r.ID = previous.ID
	}
	m.rules[key] = r
	return r, nil
}
func preferences() contracts.Preferences {
	return contracts.Preferences{UserID: "owner", Timezone: "Asia/Shanghai", WorkStart: 9 * 3600e6, WorkEnd: 18 * 3600e6, LunchStart: 12 * 3600e6, LunchEnd: 13 * 3600e6, WorkingWeekdays: []int32{0, 1, 2, 3, 4}, DefaultEventMinutes: 60, DefaultTaskMinutes: 30, DigestEnabled: true, DigestLocalTime: 8 * 3600e6, QuietHoursEnabled: true, QuietStart: 22 * 3600e6, QuietEnd: 7 * 3600e6}
}
func setup(t *testing.T) (*Service, *memory, *fixedClock) {
	t.Helper()
	m := &memory{getErr: contracts.ErrNotFound, aliases: map[string]contracts.Alias{}, rules: map[string]contracts.MailRule{}}
	clock := &fixedClock{time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)}
	s, err := New(m, preferences(), clock)
	if err != nil {
		t.Fatal(err)
	}
	return s, m, clock
}

func TestOwnerPreferencesAliasesAndMailRules(t *testing.T) {
	s, m, _ := setup(t)
	ctx := context.Background()
	p, err := s.Preferences(ctx, "owner")
	if err != nil || p.Timezone != "Asia/Shanghai" {
		t.Fatal("defaults not initialized", err)
	}
	m.preferences.DefaultTaskMinutes = 45
	p, err = s.Preferences(ctx, "owner")
	if err != nil || p.DefaultTaskMinutes != 45 {
		t.Fatal("stored preferences overwritten")
	}
	first, err := s.RegisterAlias(ctx, "owner", "  Straẞe\t Owner ")
	if err != nil || first.Value != "Straẞe Owner" {
		t.Fatal("alias normalization failed", err)
	}
	second, err := s.RegisterAlias(ctx, "owner", "strasse owner")
	if err != nil || second != first {
		t.Fatal("Unicode casefold idempotency lost")
	}
	aliases, _ := s.Aliases(ctx, "owner")
	if len(aliases) != 1 {
		t.Fatal("duplicate aliases")
	}
	rule, err := s.RegisterMailRule(ctx, "owner", contracts.Sender, "  Example  Subject  ", contracts.Notify)
	if err != nil {
		t.Fatal(err)
	}
	updated, err := s.RegisterMailRule(ctx, "owner", contracts.Sender, "example subject", contracts.Hold)
	if err != nil || updated.ID != rule.ID || updated.Action != contracts.Hold {
		t.Fatal("rule upsert failed")
	}
	if rules, err := s.MailRules(ctx, "owner"); err != nil || len(rules) != 1 {
		t.Fatal("mail rules unavailable")
	}
	if _, err := s.Preferences(ctx, "other"); err == nil {
		t.Fatal("non-owner preferences allowed")
	}
	if _, err := s.Aliases(ctx, "other"); err == nil {
		t.Fatal("non-owner aliases allowed")
	}
	if _, err := s.RegisterAlias(ctx, "other", "alias"); err == nil {
		t.Fatal("non-owner alias write allowed")
	}
	if _, err := s.MailRules(ctx, "other"); err == nil {
		t.Fatal("non-owner rules allowed")
	}
	if _, err := s.RegisterMailRule(ctx, "other", contracts.Sender, "pattern", contracts.Hold); err == nil {
		t.Fatal("non-owner rule write allowed")
	}
	for _, value := range []string{" ", strings.Repeat("张", 65)} {
		if _, err := s.RegisterAlias(ctx, "owner", value); err == nil {
			t.Fatal("invalid alias accepted")
		}
	}
	for _, value := range []string{" ", strings.Repeat("张", 241)} {
		if _, err := s.RegisterMailRule(ctx, "owner", contracts.Sender, value, contracts.Hold); err == nil {
			t.Fatal("invalid pattern accepted")
		}
	}
	for _, pair := range [][2]string{{"OTHER", "HOLD"}, {"SENDER", "OTHER"}} {
		if _, err := s.RegisterMailRule(ctx, "owner", contracts.MatchField(pair[0]), "pattern", contracts.RuleAction(pair[1])); err == nil {
			t.Fatal("invalid rule enum accepted")
		}
	}
	m.getErr = contracts.ErrStorage
	if _, err := s.Preferences(ctx, "owner"); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("read failure hidden")
	}
	m.getErr = contracts.ErrNotFound
	m.initErr = contracts.ErrStorage
	if _, err := s.Preferences(ctx, "owner"); !errors.Is(err, contracts.ErrStorage) {
		t.Fatal("init failure hidden")
	}
	m.getErr = nil
	m.preferences.Timezone = "Invalid"
	if _, err := s.Preferences(ctx, "owner"); err == nil {
		t.Fatal("corrupted preferences accepted")
	}
}

func TestPreferenceValidationBranches(t *testing.T) {
	for name, mutate := range map[string]func(*contracts.Preferences){"owner": func(p *contracts.Preferences) { p.UserID = "other" }, "timezone": func(p *contracts.Preferences) { p.Timezone = "Invalid" }, "empty timezone": func(p *contracts.Preferences) { p.Timezone = "" }, "work order": func(p *contracts.Preferences) { p.WorkEnd = p.WorkStart }, "lunch bounds": func(p *contracts.Preferences) { p.LunchStart = p.WorkStart - 1 }, "time bounds": func(p *contracts.Preferences) { p.DigestLocalTime = -1 }, "weekdays empty": func(p *contracts.Preferences) { p.WorkingWeekdays = nil }, "weekdays duplicate": func(p *contracts.Preferences) { p.WorkingWeekdays = []int32{0, 0} }, "weekdays range": func(p *contracts.Preferences) { p.WorkingWeekdays = []int32{7} }, "duration": func(p *contracts.Preferences) { p.DefaultTaskMinutes = 0 }, "quiet window": func(p *contracts.Preferences) { p.QuietEnd = p.QuietStart }} {
		t.Run(name, func(t *testing.T) {
			p := preferences()
			mutate(&p)
			if err := domain.Validate(p); err == nil {
				t.Fatal("invalid preferences accepted")
			}
			_, m, c := setup(t)
			if _, err := New(m, p, c); err == nil {
				t.Fatal("invalid defaults accepted")
			}
		})
	}
	_, m, c := setup(t)
	if _, err := New(nil, preferences(), c); err == nil {
		t.Fatal("nil repository accepted")
	}
	if _, err := New(m, preferences(), nil); err == nil {
		t.Fatal("nil clock accepted")
	}
}

func TestOwnerSessionSignVerifyExpiryAndTamper(t *testing.T) {
	_, _, clock := setup(t)
	s, err := NewSessions(secret.New(strings.Repeat("s", 32)), clock)
	if err != nil {
		t.Fatal(err)
	}
	token, err := s.Issue("owner", 15*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	session, err := s.Verify(token)
	if err != nil || session.UserID != "owner" || !session.ExpiresAt.Equal(clock.now.Add(15*time.Minute)) {
		t.Fatal("session verification failed")
	}
	if strings.Contains(token.String(), token.Reveal()) {
		t.Fatal("session logged")
	}
	for _, value := range []string{"", token.Reveal() + "tampered", "a.b", strings.Repeat("x", 4097)} {
		if _, err := s.Verify(secret.New(value)); err == nil {
			t.Fatal("invalid session accepted")
		}
	}
	for _, payload := range []string{`not json`, `{"sub":"other","exp":1792368900,"jti":"synthetic-long-id"}`, `{"sub":"owner","exp":9999999999,"jti":"synthetic-long-id"}`, `{"sub":"owner","exp":1792368900,"jti":"x"}`, `{"sub":"owner","exp":1792368900,"jti":"synthetic-long-id","unknown":true}`} {
		encoded := base64.RawURLEncoding.EncodeToString([]byte(payload))
		if _, err := s.Verify(secret.New(encoded + "." + s.signature(encoded))); err == nil {
			t.Fatal("invalid signed session payload accepted")
		}
	}
	encoded := "!"
	if _, err := s.Verify(secret.New(encoded + "." + s.signature(encoded))); err == nil {
		t.Fatal("invalid base64 accepted")
	}
	clock.now = session.ExpiresAt
	if _, err := s.Verify(token); err == nil {
		t.Fatal("expired session accepted")
	}
	for _, duration := range []time.Duration{0, -time.Minute, 2 * time.Hour} {
		if _, err := s.Issue("owner", duration); err == nil {
			t.Fatal("unbounded session lifetime")
		}
	}
	if _, err := s.Issue("other", time.Minute); err == nil {
		t.Fatal("non-owner session issued")
	}
	clock.now = time.Time{}
	if _, err := s.Issue("owner", time.Minute); err == nil {
		t.Fatal("zero clock accepted")
	}
	if _, err := NewSessions(secret.New("short"), clock); err == nil {
		t.Fatal("short signing key accepted")
	}
	if _, err := NewSessions(secret.New(strings.Repeat("s", 32)), nil); err == nil {
		t.Fatal("nil clock accepted")
	}
}
