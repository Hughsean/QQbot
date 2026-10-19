// Package accountprobe provides a bounded, nonpersistent Microsoft sandbox.
// It never touches the business database, mail content, To Do lists or QQ.
package accountprobe

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"encoding/base64"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/secret"
)

type Probe struct {
	provider             application.MicrosoftProvider
	clock                clock.Clock
	mutex                sync.Mutex
	flow, browser, state secret.Value
	expires              time.Time
	started, consumed    bool
	done                 chan error
}

func New(provider application.MicrosoftProvider, timeSource clock.Clock) (*Probe, error) {
	if provider == nil || timeSource == nil {
		return nil, contracts.ErrInvalid
	}
	return &Probe{provider: provider, clock: timeSource, done: make(chan error, 1)}, nil
}
func (p *Probe) Done() <-chan error { return p.done }
func random() secret.Value {
	value := make([]byte, 32)
	if _, err := rand.Read(value); err != nil {
		panic("secure random source unavailable")
	}
	return secret.New(base64.RawURLEncoding.EncodeToString(value))
}

func (p *Probe) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("X-Frame-Options", "DENY")
	if r.Host != "localhost:8000" || r.Method != http.MethodGet {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	if r.URL.Path == "/" {
		p.begin(w, r)
		return
	}
	if r.URL.Path != "/oauth/microsoft/callback" || len(r.URL.RawQuery) > 32768 {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	p.complete(w, r)
}

func (p *Probe) begin(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Sec-Fetch-Site") == "cross-site" {
		w.WriteHeader(http.StatusForbidden)
		return
	}
	p.mutex.Lock()
	defer p.mutex.Unlock()
	if p.started {
		w.WriteHeader(http.StatusConflict)
		return
	}
	p.started = true
	p.state, p.browser = random(), random()
	start, err := p.provider.Begin(r.Context(), p.state)
	if err != nil {
		p.done <- err
		w.WriteHeader(http.StatusBadGateway)
		return
	}
	p.started, p.flow, p.expires = true, start.Flow, p.clock.Now().Add(10*time.Minute)
	http.SetCookie(w, &http.Cookie{Name: "qq_go_account_probe", Value: p.browser.Reveal(), Path: "/", HttpOnly: true, MaxAge: 600, SameSite: http.SameSiteLaxMode})
	w.Header().Set("Location", start.URL.Reveal())
	w.WriteHeader(http.StatusFound)
}

func (p *Probe) complete(w http.ResponseWriter, r *http.Request) {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	cookie, err := r.Cookie("qq_go_account_probe")
	if err != nil || !p.validCallback(r, cookie.Value) {
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	p.consumed = true
	defer func() { p.flow, p.browser, p.state = secret.Value{}, secret.Value{}, secret.Value{} }()
	http.SetCookie(w, &http.Cookie{Name: "qq_go_account_probe", Path: "/", MaxAge: -1, HttpOnly: true, SameSite: http.SameSiteLaxMode})
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	err = p.verify(ctx, contracts.Callback{State: secret.New(r.URL.Query().Get("state")), Code: secret.New(r.URL.Query().Get("code")), ErrorCode: r.URL.Query().Get("error")})
	if err != nil {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = io.WriteString(w, "Microsoft sandbox failed. No credentials were saved.")
	} else {
		_, _ = io.WriteString(w, "Microsoft sandbox passed: PKCE, OIDC, profile, mail refresh and task refresh. No credentials were saved.")
	}
	p.done <- err
}

func (p *Probe) validCallback(r *http.Request, browser string) bool {
	return p.started && !p.consumed && p.clock.Now().Before(p.expires) && hmac.Equal([]byte(browser), []byte(p.browser.Reveal())) && hmac.Equal([]byte(r.URL.Query().Get("state")), []byte(p.state.Reveal()))
}

func (p *Probe) verify(ctx context.Context, callback contracts.Callback) error {
	tokens, err := p.provider.Complete(ctx, p.flow, callback)
	if err != nil {
		return err
	}
	profile, err := p.provider.Profile(ctx, tokens.AccessToken)
	if err != nil {
		return err
	}
	for _, tasks := range []bool{false, true} {
		refreshed, err := p.provider.Refresh(ctx, tokens.RefreshToken, tasks)
		if err != nil {
			return err
		}
		current, err := p.provider.Profile(ctx, refreshed.AccessToken)
		if err != nil {
			return err
		}
		if !strings.EqualFold(profile.AccountID.Reveal(), current.AccountID.Reveal()) {
			return contracts.ErrSecurity
		}
		if refreshed.RefreshToken.Present() {
			tokens.RefreshToken = refreshed.RefreshToken
		}
	}
	return nil
}
