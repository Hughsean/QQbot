package microsoft

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/secret"
)

func TestFlowStateExpiryAndMissingTokensFailClosed(t *testing.T) {
	c, clock := testClient(t)
	ctx := context.Background()
	state := secret.New(strings.Repeat("s", 43))
	start, err := c.Begin(ctx, state)
	if err != nil {
		t.Fatal(err)
	}
	var flow flowState
	if json.Unmarshal([]byte(start.Flow.Reveal()), &flow) != nil {
		t.Fatal("invalid generated flow")
	}
	callback := contracts.Callback{State: state, Code: secret.New("synthetic-code")}
	for _, mutate := range []func(*flowState, *contracts.Callback){
		func(f *flowState, c *contracts.Callback) { f.Expires = clock.now.Unix() }, func(f *flowState, c *contracts.Callback) { f.Expires = clock.now.Add(time.Hour).Unix() },
		func(f *flowState, c *contracts.Callback) { f.Verifier = "" }, func(f *flowState, c *contracts.Callback) { f.Nonce = "" }, func(f *flowState, c *contracts.Callback) { c.State = secret.New("different") },
		func(f *flowState, c *contracts.Callback) { c.Code = secret.Value{} }, func(f *flowState, c *contracts.Callback) { c.Code = secret.New(strings.Repeat("x", 16385)) }, func(f *flowState, c *contracts.Callback) { c.ErrorCode = "access_denied" },
	} {
		copy, cb := flow, callback
		mutate(&copy, &cb)
		data, _ := json.Marshal(copy)
		if _, err := c.Complete(ctx, secret.New(string(data)), cb); err == nil {
			t.Fatal("invalid OAuth flow accepted")
		}
	}
	if _, err := c.Complete(ctx, secret.New("bad json"), callback); err == nil {
		t.Fatal("invalid flow JSON accepted")
	}
	for _, value := range []string{"", strings.Repeat("s", 129)} {
		if _, err := c.Begin(ctx, secret.New(value)); err == nil {
			t.Fatal("unbounded state accepted")
		}
	}
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) { return response(401, "synthetic-private"), nil })
	if _, err := c.Complete(ctx, start.Flow, callback); err == nil {
		t.Fatal("failed code exchange accepted")
	}
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) { return response(200, `{"id_token":"bad"}`), nil })
	if _, err := c.Complete(ctx, start.Flow, callback); err == nil {
		t.Fatal("invalid ID token accepted")
	}
	for _, response := range []tokenResponse{{}, {Access: "synthetic", Type: "Basic", Expires: 1}, {Access: "synthetic", Type: "Bearer", Expires: -1}, {Access: "synthetic", Type: "Bearer", Expires: 86401}} {
		if _, err := c.tokens(response, authScopes); err == nil {
			t.Fatal("invalid token response accepted")
		}
	}
	tokens, err := c.tokens(tokenResponse{Access: "synthetic", Type: "Bearer", Expires: 1, Scope: "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read"}, authScopes)
	if err != nil || len(tokens.Capabilities) != 2 {
		t.Fatal("Graph scopes not normalized")
	}
	for _, config := range []Config{{ClientID: "bad", Tenant: "common", RedirectURI: c.config.RedirectURI}, {ClientID: c.config.ClientID, Tenant: "https://evil.example", RedirectURI: c.config.RedirectURI}, {ClientID: c.config.ClientID, Tenant: "common", RedirectURI: "https://evil.example/callback"}} {
		if _, err := New(config, clock); err == nil {
			t.Fatal("unsafe provider configuration accepted")
		}
	}
	if _, err := New(c.config, nil); err == nil {
		t.Fatal("missing clock accepted")
	}
	for _, body := range []string{`{}`, `{"keys":[]}`, `{"keys":[{"kty":"unsupported"}]}`, "invalid"} {
		if _, err := decodeKeys([]byte(body)); err == nil {
			t.Fatal("invalid keys accepted")
		}
	}
	for _, body := range []string{`{}`, `invalid`} {
		c.http.Transport = transport(func(*http.Request) (*http.Response, error) { return response(200, body), nil })
		if _, err := c.Profile(ctx, secret.New("synthetic")); err == nil {
			t.Fatal("invalid profile accepted")
		}
	}
}
