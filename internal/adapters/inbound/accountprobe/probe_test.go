package accountprobe

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/secret"
)

type fixedClock struct{ now time.Time }

func (c *fixedClock) Now() time.Time { return c.now }

type provider struct {
	beginErr, exchangeErr, profileErr, refreshErr error
	other                                         bool
	profiles, refreshes                           int
}

func (p *provider) Begin(context.Context, secret.Value) (application.ProviderAuthorization, error) {
	return application.ProviderAuthorization{URL: secret.New("https://login.microsoftonline.com/synthetic"), Flow: secret.New("synthetic-private")}, p.beginErr
}
func (p *provider) Complete(context.Context, secret.Value, contracts.Callback) (application.Tokens, error) {
	return application.Tokens{AccessToken: secret.New("synthetic-private"), RefreshToken: secret.New("synthetic-refresh")}, p.exchangeErr
}
func (p *provider) Refresh(context.Context, secret.Value, bool) (application.Tokens, error) {
	p.refreshes++
	return application.Tokens{AccessToken: secret.New("synthetic-private"), RefreshToken: secret.New("synthetic-rotated")}, p.refreshErr
}
func (p *provider) Profile(context.Context, secret.Value) (application.Profile, error) {
	p.profiles++
	id := "synthetic-account"
	if p.other && p.profiles > 1 {
		id = "other"
	}
	return application.Profile{AccountID: secret.New(id)}, p.profileErr
}
func setup(t *testing.T) (*Probe, *provider, *fixedClock) {
	t.Helper()
	provider := &provider{}
	clock := &fixedClock{time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)}
	p, err := New(provider, clock)
	if err != nil {
		t.Fatal(err)
	}
	return p, provider, clock
}
func serve(p *Probe, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r := httptest.NewRequest("GET", "http://localhost:8000"+path, nil)
	if p.browser.Present() {
		r.AddCookie(&http.Cookie{Name: "qq_go_account_probe", Value: p.browser.Reveal()})
	}
	p.ServeHTTP(w, r)
	return w
}

func TestSandboxSuccessIsSingleUseAndNonpersistent(t *testing.T) {
	p, provider, _ := setup(t)
	w := serve(p, "/")
	if w.Code != 302 || len(w.Result().Cookies()) != 1 || !w.Result().Cookies()[0].HttpOnly {
		t.Fatal("probe start failed")
	}
	state := p.state.Reveal()
	w = serve(p, "/oauth/microsoft/callback?state="+state+"&code=synthetic-private")
	if w.Code != 200 || strings.Contains(w.Body.String(), "synthetic-private") {
		t.Fatal("probe failed or leaked data")
	}
	if err := <-p.Done(); err != nil {
		t.Fatal(err)
	}
	if provider.profiles != 3 || provider.refreshes != 2 || p.flow.Present() || p.state.Present() || p.browser.Present() {
		t.Fatal("probe did not verify/clear transient credentials")
	}
	if w := serve(p, "/oauth/microsoft/callback?state="+state); w.Code != 400 {
		t.Fatal("probe callback replayed")
	}
	if w := serve(p, "/"); w.Code != 409 {
		t.Fatal("probe authorization repeated")
	}
}

func TestProbeRefusesForeignRequestsAndExpiredState(t *testing.T) {
	p, _, clock := setup(t)
	for _, path := range []string{"/unknown", "/oauth/microsoft/callback?" + strings.Repeat("x", 32769)} {
		if w := serve(p, path); w.Code != 404 {
			t.Fatal("unknown/oversize request accepted")
		}
	}
	r := httptest.NewRequest("GET", "http://evil.example/", nil)
	w := httptest.NewRecorder()
	p.ServeHTTP(w, r)
	if w.Code != 404 {
		t.Fatal("foreign Host accepted")
	}
	r = httptest.NewRequest("POST", "http://localhost:8000/", nil)
	w = httptest.NewRecorder()
	p.ServeHTTP(w, r)
	if w.Code != 404 {
		t.Fatal("unexpected method accepted")
	}
	r = httptest.NewRequest("GET", "http://localhost:8000/", nil)
	r.Header.Set("Sec-Fetch-Site", "cross-site")
	w = httptest.NewRecorder()
	p.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal("cross-site bootstrap accepted")
	}
	serve(p, "/")
	if w := serve(p, "/oauth/microsoft/callback?state=wrong"); w.Code != 400 || p.consumed {
		t.Fatal("wrong state accepted or consumed session")
	}
	clock.now = clock.now.Add(10 * time.Minute)
	if w := serve(p, "/oauth/microsoft/callback?state="+p.state.Reveal()); w.Code != 400 {
		t.Fatal("expired callback accepted")
	}
	if _, err := New(nil, clock); err == nil {
		t.Fatal("nil provider accepted")
	}
	if _, err := New(&provider{}, nil); err == nil {
		t.Fatal("nil clock accepted")
	}
}

func TestProbeFailuresAreRedacted(t *testing.T) {
	for _, inject := range []func(*provider){func(p *provider) { p.beginErr = errors.New("synthetic-private") }, func(p *provider) { p.exchangeErr = errors.New("synthetic-private") }, func(p *provider) { p.profileErr = errors.New("synthetic-private") }, func(p *provider) { p.refreshErr = errors.New("synthetic-private") }, func(p *provider) { p.other = true }} {
		p, provider, _ := setup(t)
		inject(provider)
		w := serve(p, "/")
		if w.Code == 302 {
			w = serve(p, "/oauth/microsoft/callback?state="+p.state.Reveal()+"&code=synthetic-private")
		}
		if w.Code < 400 || strings.Contains(w.Body.String(), "synthetic-private") {
			t.Fatal("probe failure leaked secret")
		}
		if err := <-p.Done(); err == nil || strings.Contains(err.Error(), "synthetic-private") {
			t.Fatal("probe failure hidden")
		}
	}
}

func TestProbeReportsFixedFailureStageAndClass(t *testing.T) {
	for _, input := range []struct {
		stage  string
		inject func(*provider)
	}{
		{"authorization_start", func(p *provider) { p.beginErr = contracts.ProviderError{Class: "TransientProvider"} }},
		{"code_exchange_and_oidc", func(p *provider) { p.exchangeErr = contracts.ProviderError{Class: "TransientProvider"} }},
		{"initial_profile", func(p *provider) { p.profileErr = contracts.ProviderError{Class: "TransientProvider"} }},
		{"mail_refresh", func(p *provider) { p.refreshErr = contracts.ProviderError{Class: "TransientProvider"} }},
	} {
		p, provider, _ := setup(t)
		input.inject(provider)
		if serve(p, "/").Code == 302 {
			serve(p, "/oauth/microsoft/callback?state="+p.state.Reveal()+"&code=synthetic")
		}
		err := <-p.Done()
		var classified contracts.ProviderError
		if !strings.Contains(err.Error(), input.stage) || !errors.As(err, &classified) || classified.Class != "TransientProvider" {
			t.Fatal("fixed stage/class missing", err)
		}
	}
	if err := stageFailure("test", contracts.ProviderError{Class: "synthetic-private"}); strings.Contains(err.Error(), "synthetic-private") {
		t.Fatal("unrecognized provider class leaked")
	}
}
