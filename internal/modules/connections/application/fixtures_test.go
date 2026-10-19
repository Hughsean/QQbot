package application

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	audit "qqtimeagent/internal/modules/audit/contracts"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
	credentials "qqtimeagent/internal/modules/credentials/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

type fixedClock struct{ now time.Time }

func (c *fixedClock) Now() time.Time { return c.now }

type memoryRepository struct {
	rows                                                map[string]domain.Connection
	transactions                                        map[string]domain.OAuthTransaction
	addErr, saveErr, listErr, getErr, authErr, claimErr error
}

func (r *memoryRepository) Add(_ context.Context, c domain.Connection) error {
	if r.addErr != nil {
		return r.addErr
	}
	r.rows[c.ID] = c
	return nil
}
func (r *memoryRepository) Get(_ context.Context, id, user string) (domain.Connection, error) {
	if r.getErr != nil {
		return domain.Connection{}, r.getErr
	}
	c, ok := r.rows[id]
	if !ok || c.UserID != user {
		return c, contracts.ErrNotFound
	}
	return c, nil
}
func (r *memoryRepository) List(_ context.Context, user string, p domain.Provider) ([]domain.Connection, error) {
	if r.listErr != nil {
		return nil, r.listErr
	}
	result := []domain.Connection{}
	for _, c := range r.rows {
		if c.UserID == user && c.Provider == p {
			result = append(result, c)
		}
	}
	return result, nil
}
func (r *memoryRepository) Save(_ context.Context, c domain.Connection, expected int) error {
	if r.saveErr != nil {
		return r.saveErr
	}
	previous, ok := r.rows[c.ID]
	if !ok || previous.Version != expected {
		return contracts.ErrConflict
	}
	r.rows[c.ID] = c
	return nil
}
func (r *memoryRepository) SaveDisconnected(ctx context.Context, c domain.Connection, expected int, now time.Time) error {
	if err := r.Save(ctx, c, expected); err != nil {
		return err
	}
	for key, t := range r.transactions {
		if t.ConnectionID == c.ID && t.ConsumedAt == nil {
			t.ConsumedAt = &now
			r.transactions[key] = t
		}
	}
	return nil
}
func (r *memoryRepository) AddAuthorization(ctx context.Context, c domain.Connection, expected int, t domain.OAuthTransaction) error {
	if r.authErr != nil {
		return r.authErr
	}
	if expected == 0 {
		r.Add(ctx, c)
	} else if err := r.Save(ctx, c, expected); err != nil {
		return err
	}
	r.transactions[string(t.StateHash)] = t
	return nil
}
func (r *memoryRepository) ClaimTransaction(_ context.Context, state, browser []byte, now time.Time) (domain.OAuthTransaction, error) {
	if r.claimErr != nil {
		return domain.OAuthTransaction{}, r.claimErr
	}
	t, ok := r.transactions[string(state)]
	if !ok {
		return t, contracts.ErrSecurity
	}
	if err := t.Claim(state, browser, now); err != nil {
		return t, err
	}
	r.transactions[string(state)] = t
	return t, nil
}

type memoryVault struct {
	rows                                     map[string]credentials.Handle
	storeErr, openErr, replaceErr, deleteErr error
	deletes                                  int
	events                                   *[]string
}

func (v *memoryVault) Store(_ context.Context, value secret.Value, kind credentials.Kind, expires *time.Time) (credentials.Ref, error) {
	if v.storeErr != nil {
		return credentials.Ref{}, v.storeErr
	}
	id := ids.New()
	v.rows[id] = credentials.NewHandle(value, kind, expires)
	return credentials.Ref{ID: id}, nil
}
func (v *memoryVault) Open(_ context.Context, ref credentials.Ref) (credentials.Handle, error) {
	if v.openErr != nil {
		return credentials.Handle{}, v.openErr
	}
	h, ok := v.rows[ref.ID]
	if !ok {
		return h, credentials.ErrNotFound
	}
	return h, nil
}
func (v *memoryVault) Replace(_ context.Context, ref credentials.Ref, value secret.Value) error {
	if v.replaceErr != nil {
		return v.replaceErr
	}
	h, ok := v.rows[ref.ID]
	if !ok {
		return credentials.ErrNotFound
	}
	v.rows[ref.ID] = credentials.NewHandle(value, h.Kind(), nil)
	return nil
}
func (v *memoryVault) Delete(_ context.Context, ref credentials.Ref) (bool, error) {
	if v.deleteErr != nil {
		return false, v.deleteErr
	}
	v.deletes++
	*v.events = append(*v.events, "credential-delete")
	_, ok := v.rows[ref.ID]
	delete(v.rows, ref.ID)
	return ok, nil
}

type effects struct {
	events                                             []string
	allowErr, blockErr, deleteErr, cancelErr, auditErr error
}

func (e *effects) AllowConnection(context.Context, string) error {
	e.events = append(e.events, "allow")
	return e.allowErr
}
func (e *effects) BlockConnection(context.Context, string) error {
	e.events = append(e.events, "block")
	return e.blockErr
}
func (e *effects) DeleteConnectionSources(context.Context, string) error {
	e.events = append(e.events, "source-delete")
	return e.deleteErr
}
func (e *effects) CancelForConnection(context.Context, string, time.Time) error {
	e.events = append(e.events, "cancel")
	return e.cancelErr
}
func (e *effects) AppendConnection(_ context.Context, event audit.ConnectionEvent) error {
	e.events = append(e.events, "audit:"+event.Kind)
	return e.auditErr
}

type guard struct {
	mutex sync.Mutex
	err   error
}

func (g *guard) Run(ctx context.Context, _ domain.Provider, work func(context.Context) error) error {
	if g.err != nil {
		return g.err
	}
	g.mutex.Lock()
	defer g.mutex.Unlock()
	return work(ctx)
}

type fingerprinter struct{ err error }

func (f *fingerprinter) Fingerprint(p, id string) (string, error) {
	if f.err != nil {
		return "", f.err
	}
	if id == "" {
		return "", contracts.ErrInvalid
	}
	return p + "|" + id, nil
}

type provider struct {
	state                                         secret.Value
	beginErr, completeErr, refreshErr, profileErr error
	tokens                                        Tokens
	profile                                       Profile
	completes                                     int
}

func (p *provider) Begin(_ context.Context, state secret.Value) (ProviderAuthorization, error) {
	p.state = state
	return ProviderAuthorization{URL: secret.New("https://synthetic.example/authorize"), Flow: secret.New("synthetic-flow")}, p.beginErr
}
func (p *provider) Complete(context.Context, secret.Value, contracts.Callback) (Tokens, error) {
	p.completes++
	return p.tokens, p.completeErr
}
func (p *provider) Refresh(context.Context, secret.Value, bool) (Tokens, error) {
	return p.tokens, p.refreshErr
}
func (p *provider) Profile(context.Context, secret.Value) (Profile, error) {
	return p.profile, p.profileErr
}

type verifier struct{ err error }

func (v *verifier) Verify(context.Context, secret.Value, secret.Value) error { return v.err }

type fixture struct {
	s             *Service
	m             *Microsoft
	q             *QQMail
	repo          *memoryRepository
	vault         *memoryVault
	effects       *effects
	provider      *provider
	clock         *fixedClock
	guard         *guard
	fingerprinter *fingerprinter
	verifier      *verifier
}

func setup(t *testing.T) *fixture {
	t.Helper()
	f := &fixture{repo: &memoryRepository{rows: map[string]domain.Connection{}, transactions: map[string]domain.OAuthTransaction{}}, effects: &effects{}, clock: &fixedClock{time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)}, guard: &guard{}, fingerprinter: &fingerprinter{}, verifier: &verifier{}}
	f.vault = &memoryVault{rows: map[string]credentials.Handle{}, events: &f.effects.events}
	f.provider = &provider{tokens: Tokens{AccessToken: secret.New("synthetic-access"), RefreshToken: secret.New("synthetic-refresh"), ExpiresAt: f.clock.now.Add(time.Hour), Capabilities: []string{"Mail.Read", "User.Read", "Tasks.ReadWrite"}}, profile: Profile{AccountID: secret.New("synthetic-account"), Email: secret.New("synthetic@example.test")}}
	var err error
	f.s, err = New(Dependencies{Repository: f.repo, Vault: f.vault, Clock: f.clock, Fingerprinter: f.fingerprinter, Sources: f.effects, Jobs: f.effects, Guard: f.guard, Audit: f.effects})
	if err != nil {
		t.Fatal(err)
	}
	f.m, err = NewMicrosoft(f.s, f.provider)
	if err != nil {
		t.Fatal(err)
	}
	f.q, err = NewQQMail(f.s, f.verifier)
	if err != nil {
		t.Fatal(err)
	}
	return f
}
func (f *fixture) start(t *testing.T, id string) (contracts.Authorization, contracts.Callback) {
	t.Helper()
	start, err := f.m.Begin(context.Background(), "owner", id)
	if err != nil {
		t.Fatal(err)
	}
	return start, contracts.Callback{State: f.provider.state, Code: secret.New("synthetic-code")}
}
func (f *fixture) active(t *testing.T) contracts.View {
	t.Helper()
	start, callback := f.start(t, "")
	view, err := f.m.Complete(context.Background(), callback, start.BrowserSession)
	if err != nil {
		t.Fatal(err)
	}
	return view
}

var errFailure = errors.New("synthetic persistence unavailable")
