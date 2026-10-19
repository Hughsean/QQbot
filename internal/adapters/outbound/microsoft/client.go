// Package microsoft implements the public-client OAuth and read-only profile ports.
package microsoft

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/url"
	"strings"
	"time"

	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

const authority = "https://login.microsoftonline.com/"
const graph = "https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName"
const consumerTenant = "9188040d-6c67-4c5b-b112-36a304b66dad"
const authScopes = "openid profile email offline_access User.Read Mail.Read Tasks.ReadWrite"

type Config struct{ ClientID, Tenant, RedirectURI string }

type Client struct {
	config Config
	clock  clock.Clock
	http   *http.Client
	keys   *keyCache
}

func New(config Config, timeSource clock.Clock) (*Client, error) {
	if ids.Validate(config.ClientID) != nil || !validTenant(config.Tenant) || config.RedirectURI != "http://localhost:8000/oauth/microsoft/callback" || timeSource == nil {
		return nil, contracts.ErrInvalid
	}
	client := &http.Client{Timeout: 12 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	return &Client{config: config, clock: timeSource, http: client, keys: &keyCache{}}, nil
}

func validTenant(tenant string) bool {
	return tenant == "common" || tenant == "consumers" || tenant == "organizations" || ids.Validate(tenant) == nil
}

type flowState struct {
	State    string `json:"state"`
	Verifier string `json:"verifier"`
	Nonce    string `json:"nonce"`
	Expires  int64  `json:"expires"`
}

func randomSecret() string {
	value := make([]byte, 32)
	if _, err := rand.Read(value); err != nil {
		panic("secure random source unavailable")
	}
	return base64.RawURLEncoding.EncodeToString(value)
}

func (c *Client) Begin(_ context.Context, state secret.Value) (application.ProviderAuthorization, error) {
	if len(state.Reveal()) < 32 || len(state.Reveal()) > 128 {
		return application.ProviderAuthorization{}, contracts.ErrSecurity
	}
	flow := flowState{State: state.Reveal(), Verifier: randomSecret(), Nonce: randomSecret(), Expires: c.clock.Now().Add(10 * time.Minute).Unix()}
	challenge := sha256.Sum256([]byte(flow.Verifier))
	query := url.Values{"client_id": {c.config.ClientID}, "response_type": {"code"}, "redirect_uri": {c.config.RedirectURI}, "response_mode": {"query"}, "scope": {authScopes}, "state": {flow.State}, "nonce": {flow.Nonce}, "code_challenge_method": {"S256"}, "code_challenge": {base64.RawURLEncoding.EncodeToString(challenge[:])}}
	data, err := json.Marshal(flow)
	if err != nil {
		return application.ProviderAuthorization{}, contracts.ErrSecurity
	}
	return application.ProviderAuthorization{URL: secret.New(authority + c.config.Tenant + "/oauth2/v2.0/authorize?" + query.Encode()), Flow: secret.New(string(data))}, nil
}

func failure(class string) error { return application.ProviderError{Class: class} }

func scopes(value string) []string {
	result := make([]string, 0, 3)
	for _, expected := range []string{"Mail.Read", "Tasks.ReadWrite", "User.Read"} {
		for _, granted := range strings.Fields(value) {
			if strings.EqualFold(strings.TrimPrefix(granted, "https://graph.microsoft.com/"), expected) {
				result = append(result, expected)
				break
			}
		}
	}
	return result
}

var _ application.MicrosoftProvider = (*Client)(nil)
