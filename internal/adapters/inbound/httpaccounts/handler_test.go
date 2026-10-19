package httpaccounts

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	identity "qqtimeagent/internal/modules/identity/application"
	identitycontracts "qqtimeagent/internal/modules/identity/contracts"
	"qqtimeagent/internal/platform/secret"
)

const fixtureID = "00000000-0000-4000-8000-000000000001"

type fixedClock struct{}

func (fixedClock) Now() time.Time { return time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC) }

type manager struct {
	values       []contracts.View
	err          error
	calls        int
	lastID, code string
}

func (m *manager) Begin(_ context.Context, _ string, id string) (contracts.Authorization, error) {
	m.calls++
	m.lastID = id
	return contracts.Authorization{URL: secret.New("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?state=synthetic-state"), BrowserSession: secret.New("synthetic-browser-session")}, m.err
}
func (m *manager) Complete(_ context.Context, c contracts.Callback, b secret.Value) (contracts.View, error) {
	m.calls++
	m.code = c.Code.Reveal()
	return contracts.View{ID: fixtureID, Status: "ACTIVE"}, m.err
}
func (m *manager) Statuses(context.Context, string, string) ([]contracts.View, error) {
	m.calls++
	return m.values, m.err
}
func (m *manager) Disconnect(_ context.Context, _ string, id string, _ bool) (contracts.View, error) {
	m.calls++
	m.lastID = id
	return contracts.View{ID: id, Status: "DISCONNECTED"}, m.err
}

type mail struct {
	m             *manager
	address, code string
}

func (q *mail) Connect(_ context.Context, _ string, address, code secret.Value) (contracts.View, error) {
	q.m.calls++
	q.address = address.Reveal()
	q.code = code.Reveal()
	return contracts.View{ID: fixtureID, Status: "ACTIVE"}, q.m.err
}
func (q *mail) Statuses(ctx context.Context, user string) ([]contracts.View, error) {
	return q.m.Statuses(ctx, user, "")
}
func (q *mail) Disconnect(ctx context.Context, user, id string, confirmed bool) (contracts.View, error) {
	return q.m.Disconnect(ctx, user, id, confirmed)
}

type fixture struct {
	h        http.Handler
	m        *manager
	q        *mail
	token    secret.Value
	sessions *identity.Sessions
}

func setup(t *testing.T) *fixture {
	t.Helper()
	f := &fixture{m: &manager{values: []contracts.View{{ID: fixtureID, Default: true, Status: "ACTIVE"}}}}
	f.q = &mail{m: f.m}
	var err error
	f.sessions, err = identity.NewSessions(secret.New(strings.Repeat("k", 32)), fixedClock{})
	if err != nil {
		t.Fatal(err)
	}
	f.token, err = f.sessions.Issue("owner", 15*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	f.h, err = New(f.m, f.q, f.sessions)
	if err != nil {
		t.Fatal(err)
	}
	return f
}
func (f *fixture) request(method, path, body string, authenticated, withCSRF bool) *http.Request {
	r := httptest.NewRequest(method, "http://localhost:8000"+path, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	if authenticated {
		r.AddCookie(&http.Cookie{Name: ownerCookie, Value: f.token.Reveal()})
	}
	if withCSRF {
		r.AddCookie(&http.Cookie{Name: csrfCookie, Value: "synthetic-csrf-token"})
		r.Header.Set("X-CSRF-Token", "synthetic-csrf-token")
		r.Header.Set("Origin", "http://localhost:8000")
	}
	return r
}
func (f *fixture) serve(r *http.Request) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	f.h.ServeHTTP(w, r)
	return w
}

func TestLoopbackOwnerCookiesAndIncrementalAuthorization(t *testing.T) {
	f := setup(t)
	r := f.request("GET", "/oauth/microsoft/owner-start", "", false, false)
	r.Host = "127.0.0.1:8000"
	w := f.serve(r)
	if w.Code != 303 || w.Header().Get("Location") != "http://localhost:8000/oauth/microsoft/owner-start" || len(w.Result().Cookies()) != 0 {
		t.Fatal("canonical redirect set secrets on the wrong host")
	}
	w = f.serve(f.request("GET", "/oauth/microsoft/owner-start", "", false, false))
	if w.Code != 303 || w.Header().Get("Location") != "/oauth/microsoft/start?connection_id="+fixtureID {
		t.Fatal("default incremental authorization lost")
	}
	for _, cookie := range w.Result().Cookies() {
		if cookie.Name != ownerCookie || !cookie.HttpOnly || cookie.SameSite != http.SameSiteLaxMode || cookie.Path != "/" || cookie.MaxAge != 900 {
			t.Fatal("unsafe owner cookie")
		}
		if _, err := f.sessions.Verify(secret.New(cookie.Value)); err != nil {
			t.Fatal("invalid issued session")
		}
	}
	w = f.serve(f.request("GET", "/oauth/microsoft/start?connection_id="+fixtureID, "", true, false))
	if w.Code != 302 || f.m.lastID != fixtureID || !strings.HasPrefix(w.Header().Get("Location"), "https://login.microsoftonline.com/") {
		t.Fatal("OAuth start failed")
	}
	if len(w.Result().Cookies()) != 3 {
		t.Fatal("missing OAuth cookies")
	}
	for _, cookie := range w.Result().Cookies() {
		if cookie.Name == csrfCookie {
			if cookie.HttpOnly {
				t.Fatal("CSRF token inaccessible to same-origin page")
			}
		} else if !cookie.HttpOnly {
			t.Fatal("session not HttpOnly")
		}
	}
	if w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("Referrer-Policy") != "no-referrer" {
		t.Fatal("sensitive redirect cacheable")
	}
	form := url.Values{"session": {f.token.Reveal()}, "next": {"/qq-mail/connect"}}
	w = f.serve(f.request("POST", "/api/v1/owner/session", form.Encode(), false, false))
	if w.Code != 303 || w.Header().Get("Location") != "/qq-mail/connect" {
		t.Fatal("session establishment failed")
	}
	w = f.serve(f.request("GET", "/qq-mail/owner-start", "", false, false))
	if w.Code != 303 || w.Header().Get("Location") != "/qq-mail/connect" {
		t.Fatal("mail owner start failed")
	}
	f.m.values = nil
	w = f.serve(f.request("GET", "/oauth/microsoft/owner-start", "", false, false))
	if w.Header().Get("Location") != "/oauth/microsoft/start" {
		t.Fatal("first authorization has an ID")
	}
}

func TestCallbackNeverReflectsCodeOrProviderErrors(t *testing.T) {
	f := setup(t)
	r := f.request("GET", "/oauth/microsoft/callback?state=synthetic-state&code=synthetic-private-code", "", false, false)
	r.AddCookie(&http.Cookie{Name: oauthCookie, Value: "synthetic-browser"})
	r.Header.Set("Sec-Fetch-Site", "cross-site")
	w := f.serve(r)
	if w.Code != 200 || f.m.code != "synthetic-private-code" {
		t.Fatal("OAuth top-level callback rejected")
	}
	if strings.Contains(w.Body.String(), "synthetic-private-code") {
		t.Fatal("authorization code reflected")
	}
	if cookies := w.Result().Cookies(); len(cookies) != 1 || cookies[0].Name != oauthCookie || cookies[0].MaxAge != -1 {
		t.Fatal("OAuth cookie not cleared")
	}
	f.m.err = errors.New("synthetic-private-code provider raw response")
	w = f.serve(r)
	if w.Code != 400 || strings.Contains(w.Body.String(), "synthetic-private") {
		t.Fatal("callback error leaked")
	}
}

func TestConnectionsJSONContractsAndMailForm(t *testing.T) {
	f := setup(t)
	for _, path := range []string{"/api/v1/connections/microsoft", "/api/v1/connections/microsoft/status", "/api/v1/connections/qq-mail", "/api/v1/connections/qq-mail/status"} {
		w := f.serve(f.request("GET", path, "", true, false))
		if w.Code != 200 || !strings.Contains(w.Body.String(), fixtureID) {
			t.Fatal("connection read failed", path, w.Code)
		}
	}
	f.m.values = []contracts.View{{ID: fixtureID, Default: false}}
	w := f.serve(f.request("GET", "/api/v1/connections/microsoft/status", "", true, false))
	if strings.TrimSpace(w.Body.String()) != "null" {
		t.Fatal("legacy status guessed a nondefault connection")
	}
	r := f.request("GET", "/api/v1/connections/microsoft", "", false, false)
	r.Header.Set("X-Owner-Session", f.token.Reveal())
	if w := f.serve(r); w.Code != 200 {
		t.Fatal("owner header compatibility lost")
	}
	w = f.serve(f.request("GET", "/qq-mail/connect", "", true, false))
	if w.Code != 200 || !strings.Contains(w.Body.String(), "连接 QQ 邮箱") || !strings.Contains(w.Header().Get("Content-Security-Policy"), "script-src 'nonce-") {
		t.Fatal("mail form insecure or unavailable")
	}
	if strings.Contains(w.Body.String(), "ZgotmplZ") {
		t.Fatal("template escaped valid script data")
	}
	w = f.serve(f.request("POST", "/api/v1/connections/qq-mail", `{"address":"123@qq.com","authorization_code":"synthetic-private"}`, true, true))
	if w.Code != 200 || f.q.address != "123@qq.com" || f.q.code != "synthetic-private" || strings.Contains(w.Body.String(), "synthetic-private") {
		t.Fatal("mail connect contract failed")
	}
	for _, path := range []string{"/api/v1/oauth/microsoft/disconnect", "/api/v1/connections/qq-mail/disconnect"} {
		w := f.serve(f.request("POST", path, `{"connection_id":"`+fixtureID+`","confirmed":true}`, true, true))
		if w.Code != 200 || f.m.lastID != fixtureID {
			t.Fatal("disconnect contract failed", w.Code)
		}
	}
}

func TestSecurityAndStrictRequestValidation(t *testing.T) {
	f := setup(t)
	for _, host := range []string{"evil.example", "localhost.evil.example:8000", "[::1]:8000", "localhost:bad:8000"} {
		r := f.request("GET", "/oauth/microsoft/owner-start", "", false, false)
		r.Host = host
		r.Header.Set("X-Forwarded-Host", "localhost:8000")
		if w := f.serve(r); w.Code != 404 {
			t.Fatal("non-loopback host accepted")
		}
	}
	for _, path := range []string{"/oauth/microsoft/start", "/qq-mail/connect", "/api/v1/connections/microsoft", "/api/v1/connections/qq-mail/status"} {
		if w := f.serve(f.request("GET", path, "", false, false)); w.Code != 401 {
			t.Fatal("unauthenticated request accepted", path, w.Code)
		}
	}
	for _, input := range []struct {
		method, path, body string
		auth, csrf         bool
		status             int
	}{
		{"POST", "/api/v1/connections/qq-mail", `{}`, false, true, 401},
		{"POST", "/api/v1/connections/qq-mail", `{}`, true, false, 403},
		{"POST", "/api/v1/connections/qq-mail", `{"address":"x","authorization_code":"y","host":"evil"}`, true, true, 422},
		{"POST", "/api/v1/connections/qq-mail", `{"address":"x","authorization_code":"y"} {}`, true, true, 422},
		{"POST", "/api/v1/connections/qq-mail", `{}`, true, true, 422},
		{"POST", "/api/v1/connections/qq-mail", strings.Repeat("x", 8193), true, true, 422},
		{"POST", "/api/v1/oauth/microsoft/disconnect", `{}`, false, true, 401},
		{"POST", "/api/v1/oauth/microsoft/disconnect", `{}`, true, false, 403},
		{"POST", "/api/v1/oauth/microsoft/disconnect", `{"connection_id":"` + fixtureID + `"}`, true, true, 422},
		{"POST", "/api/v1/oauth/microsoft/disconnect", `{"connection_id":"bad","confirmed":true}`, true, true, 422},
		{"POST", "/api/v1/oauth/microsoft/disconnect", `{"connection_id":"` + fixtureID + `","confirmed":false}`, true, true, 409},
		{"GET", "/oauth/microsoft/start?session=synthetic", "", true, false, 400},
		{"GET", "/oauth/microsoft/start?connection_id=bad", "", true, false, 422},
		{"POST", "/api/v1/owner/session", "bad", false, false, 400},
		{"POST", "/api/v1/owner/session", "session=bad", false, false, 401},
		{"POST", "/api/v1/owner/session", strings.Repeat("x", 4097), false, false, 413},
	} {
		w := f.serve(f.request(input.method, input.path, input.body, input.auth, input.csrf))
		if w.Code != input.status {
			t.Fatalf("%s %s: got %d want %d", input.method, input.path, w.Code, input.status)
		}
	}
	for _, origin := range []string{"http://evil.example", "null"} {
		r := f.request("POST", "/api/v1/connections/qq-mail", `{}`, true, true)
		r.Header.Set("Origin", origin)
		if w := f.serve(r); w.Code != 403 {
			t.Fatal("foreign origin accepted")
		}
	}
	r := f.request("GET", "/oauth/microsoft/owner-start", "", false, false)
	r.Header.Set("Sec-Fetch-Site", "cross-site")
	if w := f.serve(r); w.Code != 403 {
		t.Fatal("cross-site owner bootstrap accepted")
	}
	r = f.request("POST", "/api/v1/connections/qq-mail", `{}`, true, true)
	r.Header.Set("X-CSRF-Token", "wrong")
	if w := f.serve(r); w.Code != 403 {
		t.Fatal("wrong CSRF token accepted")
	}
	r = f.request("POST", "/api/v1/connections/qq-mail", `{}`, true, true)
	r.Header.Set("Content-Type", "text/plain")
	if w := f.serve(r); w.Code != 422 {
		t.Fatal("wrong content type accepted")
	}
	form := url.Values{"session": {f.token.Reveal()}, "next": {"https://evil.example"}}
	if w := f.serve(f.request("POST", "/api/v1/owner/session", form.Encode(), false, false)); w.Code != 400 {
		t.Fatal("session open redirect accepted")
	}
}

func TestSafeErrorMappingAndRequiredPorts(t *testing.T) {
	f := setup(t)
	for _, input := range []struct {
		err    error
		status int
	}{{contracts.ErrSecurity, 401}, {contracts.ErrInvalid, 422}, {contracts.ErrConflict, 409}, {contracts.ErrNotFound, 404}, {contracts.ProviderError{Class: "Authentication"}, 401}, {errors.New("synthetic-private"), 503}} {
		f.m.err = input.err
		w := f.serve(f.request("POST", "/api/v1/connections/qq-mail", `{"address":"123@qq.com","authorization_code":"synthetic-private"}`, true, true))
		if w.Code != input.status || strings.Contains(w.Body.String(), "synthetic-private") {
			t.Fatal("unsafe error mapping", w.Code)
		}
	}
	for _, port := range []int{0, 1, 2} {
		ms, qq, signer := contracts.Manager(f.m), contracts.QQMailManager(f.q), identitycontracts.SessionAuthority(f.sessions)
		if port == 0 {
			ms = nil
		}
		if port == 1 {
			qq = nil
		}
		if port == 2 {
			signer = nil
		}
		if _, err := New(ms, qq, signer); err == nil {
			t.Fatal("missing port accepted")
		}
	}
}
