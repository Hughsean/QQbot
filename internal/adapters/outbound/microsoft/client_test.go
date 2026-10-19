package microsoft

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/go-jose/go-jose/v4"
	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/secret"
)

type fixedClock struct{ now time.Time }

func (c *fixedClock) Now() time.Time { return c.now }

type transport func(*http.Request) (*http.Response, error)

func (f transport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func response(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}
func testClient(t *testing.T) (*Client, *fixedClock) {
	t.Helper()
	clock := &fixedClock{now: time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)}
	c, err := New(Config{ClientID: "00000000-0000-4000-8000-000000000001", Tenant: "common", RedirectURI: "http://localhost:8000/oauth/microsoft/callback"}, clock)
	if err != nil {
		t.Fatal(err)
	}
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) {
		t.Fatal("unexpected external request")
		return nil, errors.New("synthetic")
	})
	return c, clock
}

type claims struct {
	Issuer   string `json:"iss"`
	Audience string `json:"aud"`
	Subject  string `json:"sub"`
	Tenant   string `json:"tid"`
	Nonce    string `json:"nonce"`
	Version  string `json:"ver"`
	Issued   int64  `json:"iat"`
	Before   int64  `json:"nbf"`
	Expires  int64  `json:"exp"`
}

func testClaims(c *Client, nonce string) claims {
	return claims{Issuer: authority + consumerTenant + "/v2.0", Audience: c.config.ClientID, Subject: "synthetic-subject", Tenant: consumerTenant, Nonce: nonce, Version: "2.0", Issued: c.clock.Now().Unix(), Before: c.clock.Now().Unix(), Expires: c.clock.Now().Add(time.Hour).Unix()}
}
func sign(t *testing.T, key *rsa.PrivateKey, payload claims, kid string) string {
	t.Helper()
	options := (&jose.SignerOptions{}).WithType("JWT").WithHeader("kid", kid)
	signer, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.RS256, Key: key}, options)
	if err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(payload)
	signed, err := signer.Sign(data)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := signed.CompactSerialize()
	if err != nil {
		t.Fatal(err)
	}
	return raw
}
func keyDocument(t *testing.T, key *rsa.PrivateKey, kid, issuer string) string {
	t.Helper()
	raw, err := json.Marshal(jose.JSONWebKey{Key: &key.PublicKey, KeyID: kid, Use: "sig", Algorithm: "RS256"})
	if err != nil {
		t.Fatal(err)
	}
	// Add Microsoft's issuer extension without an untyped claim map.
	return `{"keys":[` + strings.TrimSuffix(string(raw), "}") + `,"issuer":"` + issuer + `"}]}`
}

func TestPKCEExchangeIDTokenAndRefreshScopes(t *testing.T) {
	c, clock := testClient(t)
	ctx := context.Background()
	state := secret.New(strings.Repeat("s", 43))
	start, err := c.Begin(ctx, state)
	if err != nil {
		t.Fatal(err)
	}
	var flow flowState
	if json.Unmarshal([]byte(start.Flow.Reveal()), &flow) != nil {
		t.Fatal("invalid flow")
	}
	u, _ := url.Parse(start.URL.Reveal())
	q := u.Query()
	challenge := sha256.Sum256([]byte(flow.Verifier))
	if u.Host != "login.microsoftonline.com" || q.Get("code_challenge") != base64.RawURLEncoding.EncodeToString(challenge[:]) || q.Get("code_challenge_method") != "S256" || q.Get("nonce") != flow.Nonce || q.Get("state") != state.Reveal() {
		t.Fatal("PKCE/state/nonce not bound")
	}
	if strings.Contains(start.Flow.String(), flow.Verifier) || strings.Contains(start.URL.String(), state.Reveal()) {
		t.Fatal("authorization secrets leaked")
	}
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	jwt := sign(t, key, testClaims(c, flow.Nonce), "synthetic-key")
	var mode string
	var calls int
	c.http.Transport = transport(func(r *http.Request) (*http.Response, error) {
		calls++
		if _, ok := r.Context().Deadline(); !ok {
			t.Fatal("HTTP call has no deadline")
		}
		switch r.URL.Path {
		case "/common/discovery/v2.0/keys":
			return response(200, keyDocument(t, key, "synthetic-key", authority+"{tenantid}/v2.0")), nil
		case "/common/oauth2/v2.0/token":
			if err := r.ParseForm(); err != nil {
				t.Fatal(err)
			}
			if r.Form.Get("client_id") != c.config.ClientID || r.Form.Has("client_secret") {
				t.Fatal("not a public client")
			}
			if mode == "" {
				if r.Form.Get("code_verifier") != flow.Verifier || r.Form.Get("grant_type") != "authorization_code" {
					t.Fatal("PKCE exchange mismatch")
				}
			} else {
				if r.Form.Get("grant_type") != "refresh_token" || r.Form.Get("refresh_token") != "synthetic-refresh" {
					t.Fatal("refresh grant mismatch")
				}
				if mode == "mail" && r.Form.Get("scope") != "User.Read Mail.Read email" {
					t.Fatal("mail scope expanded")
				}
				if mode == "tasks" && r.Form.Get("scope") != "User.Read Tasks.ReadWrite" {
					t.Fatal("task scope expanded")
				}
			}
			data, _ := json.Marshal(tokenResponse{Access: "synthetic-access", Refresh: "synthetic-refresh", ID: jwt, Type: "Bearer", Expires: 3600})
			return response(200, string(data)), nil
		case "/v1.0/me":
			if r.Header.Get("Authorization") != "Bearer synthetic-access" || r.Method != "GET" {
				t.Fatal("invalid profile request")
			}
			return response(200, `{"id":"synthetic-account","mail":null,"userPrincipalName":"synthetic@example.test"}`), nil
		default:
			t.Fatalf("untrusted endpoint %s", r.URL.Host)
			return nil, errors.New("synthetic")
		}
	})
	tokens, err := c.Complete(ctx, start.Flow, contracts.Callback{State: state, Code: secret.New("synthetic-code")})
	if err != nil {
		t.Fatal(err)
	}
	if tokens.RefreshToken.Reveal() != "synthetic-refresh" || !tokens.ExpiresAt.Equal(clock.now.Add(time.Hour)) || len(tokens.Capabilities) != 3 {
		t.Fatal("tokens not converted")
	}
	profile, err := c.Profile(ctx, tokens.AccessToken)
	if err != nil || profile.AccountID.Reveal() != "synthetic-account" || profile.Email.Reveal() != "synthetic@example.test" {
		t.Fatal("profile conversion failed", err)
	}
	for _, value := range []string{"mail", "tasks"} {
		mode = value
		tokens, err = c.Refresh(ctx, secret.New("synthetic-refresh"), mode == "tasks")
		if err != nil || len(tokens.Capabilities) != 2 {
			t.Fatal("refresh failed", err)
		}
	}
	if calls != 5 {
		t.Fatalf("unexpected call count %d", calls)
	}
	// The same published key can verify a second token without another fetch.
	if err := c.verifyIDToken(ctx, jwt, flow.Nonce); err != nil || calls != 5 {
		t.Fatal("key cache not used")
	}
}

func TestIDTokenRejectsInvalidTrustChain(t *testing.T) {
	c, _ := testClient(t)
	ctx := context.Background()
	nonce := strings.Repeat("n", 43)
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	c.http.Transport = transport(func(r *http.Request) (*http.Response, error) {
		if r.URL.String() != authority+"common/discovery/v2.0/keys" {
			t.Fatal("untrusted JWKS URL")
		}
		return response(200, keyDocument(t, key, "key", authority+consumerTenant+"/v2.0")), nil
	})
	good := testClaims(c, nonce)
	if err := c.verifyIDToken(ctx, sign(t, key, good, "key"), nonce); err != nil {
		t.Fatal(err)
	}
	for name, change := range map[string]func(*claims){
		"audience": func(p *claims) { p.Audience = "another-client" }, "issuer": func(p *claims) { p.Issuer = "https://evil.example/v2.0" },
		"tenant": func(p *claims) { p.Tenant = "bad" }, "tenant issuer mismatch": func(p *claims) { p.Tenant = "00000000-0000-4000-8000-000000000002" },
		"nonce": func(p *claims) { p.Nonce = "other" }, "subject": func(p *claims) { p.Subject = "" }, "version": func(p *claims) { p.Version = "1.0" },
		"expiry": func(p *claims) { p.Expires = c.clock.Now().Unix() }, "future issued": func(p *claims) { p.Issued = c.clock.Now().Add(time.Hour).Unix() },
		"missing issued": func(p *claims) { p.Issued = 0 }, "future nbf": func(p *claims) { p.Before = c.clock.Now().Add(time.Hour).Unix() }, "missing nbf": func(p *claims) { p.Before = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			copy := good
			change(&copy)
			if err := c.verifyIDToken(ctx, sign(t, key, copy, "key"), nonce); err == nil {
				t.Fatal("invalid ID token accepted")
			}
		})
	}
	for _, raw := range []string{"bad", "a.!.b", "a." + base64.RawURLEncoding.EncodeToString([]byte("bad json")) + ".b"} {
		if err := c.verifyIDToken(ctx, raw, nonce); err == nil {
			t.Fatal("malformed JWT accepted")
		}
	}
	otherKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.verifyIDToken(ctx, sign(t, otherKey, good, "key"), nonce); err == nil {
		t.Fatal("untrusted signature accepted")
	}
	if _, err := (scopedKeySet{client: c, issuer: good.Issuer}).VerifySignature(ctx, "bad"); err == nil {
		t.Fatal("malformed signature accepted")
	}
	if _, err := (scopedKeySet{client: c, issuer: good.Issuer}).VerifySignature(ctx, sign(t, key, good, "")); err == nil {
		t.Fatal("missing kid accepted")
	}
	// A cryptographically valid signature must not escape the signing key's tenant.
	c.keys = &keyCache{}
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) {
		return response(200, keyDocument(t, key, "key", authority+"00000000-0000-4000-8000-000000000002/v2.0")), nil
	})
	if err := c.verifyIDToken(ctx, sign(t, key, good, "key"), nonce); err == nil {
		t.Fatal("tenant-scoped key used for another tenant")
	}
	c.config.Tenant = "organizations"
	if c.acceptsTenant(consumerTenant) {
		t.Fatal("consumer accepted by organizations")
	}
	c.config.Tenant = "consumers"
	if c.acceptsTenant("00000000-0000-4000-8000-000000000002") {
		t.Fatal("organization accepted by consumers")
	}
	c.config.Tenant = consumerTenant
	if !c.acceptsTenant(consumerTenant) || c.acceptsTenant("other") {
		t.Fatal("configured tenant ignored")
	}
}

func TestProviderFailuresStayBoundedAndRedacted(t *testing.T) {
	c, _ := testClient(t)
	ctx := context.Background()
	for _, input := range []struct {
		status      int
		body, class string
	}{
		{401, `{"error_description":"synthetic-private"}`, "Authentication"}, {403, "synthetic-private", "Permission"}, {429, "synthetic-private", "RateLimit"},
		{500, "synthetic-private", "TransientProvider"}, {400, `{"error":"invalid_grant","error_description":"synthetic-private"}`, "Authentication"}, {400, "synthetic-private", "PermanentProvider"},
	} {
		calls := 0
		c.http.Transport = transport(func(*http.Request) (*http.Response, error) { calls++; return response(input.status, input.body), nil })
		_, err := c.Refresh(ctx, secret.New("synthetic-private"), false)
		var provider application.ProviderError
		if !errors.As(err, &provider) || provider.Class != input.class || strings.Contains(err.Error(), "synthetic-private") || calls != 1 {
			t.Fatal("token error not classified/redacted", err)
		}
	}
	calls := 0
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) { calls++; return response(503, "synthetic-private"), nil })
	if _, err := c.Profile(ctx, secret.New("synthetic")); err == nil || calls != 2 {
		t.Fatal("GET retry budget violated")
	}
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) { return nil, errors.New("synthetic-private") })
	if _, err := c.Refresh(ctx, secret.New("synthetic"), false); err == nil || strings.Contains(err.Error(), "synthetic-private") {
		t.Fatal("transport error leaked")
	}
	for _, body := range []string{"invalid json", strings.Repeat("x", bodyLimit+1)} {
		c.http.Transport = transport(func(*http.Request) (*http.Response, error) { return response(200, body), nil })
		if _, err := c.Refresh(ctx, secret.New("synthetic"), false); err == nil {
			t.Fatal("malformed/oversize response accepted")
		}
	}
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) {
		r := response(302, "")
		r.Header.Set("Location", "https://evil.example/steal")
		return r, nil
	})
	if _, err := c.Profile(ctx, secret.New("synthetic")); err == nil {
		t.Fatal("provider redirect followed")
	}
	if _, err := c.Profile(ctx, secret.Value{}); err == nil {
		t.Fatal("empty access token accepted")
	}
	if _, err := c.Refresh(ctx, secret.Value{}, false); err == nil {
		t.Fatal("empty refresh accepted")
	}
}
