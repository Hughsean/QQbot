package microsoft

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"net/url"
	"strings"
	"time"

	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/secret"
)

type tokenResponse struct {
	Access  string `json:"access_token"`
	Refresh string `json:"refresh_token"`
	ID      string `json:"id_token"`
	Type    string `json:"token_type"`
	Expires int64  `json:"expires_in"`
	Scope   string `json:"scope"`
}

func (c *Client) Complete(ctx context.Context, stored secret.Value, callback contracts.Callback) (application.Tokens, error) {
	var flow flowState
	if json.Unmarshal([]byte(stored.Reveal()), &flow) != nil || !validFlow(flow, callback, c.clock.Now()) {
		return application.Tokens{}, contracts.ErrSecurity
	}
	form := url.Values{"grant_type": {"authorization_code"}, "code": {callback.Code.Reveal()}, "code_verifier": {flow.Verifier}, "scope": {authScopes}}
	response, err := c.exchange(ctx, form)
	if err != nil {
		return application.Tokens{}, err
	}
	if err := c.verifyIDToken(ctx, response.ID, flow.Nonce); err != nil {
		return application.Tokens{}, err
	}
	if response.Refresh == "" {
		return application.Tokens{}, failure("Authentication")
	}
	return c.tokens(response, authScopes)
}

func validFlow(flow flowState, callback contracts.Callback, now time.Time) bool {
	if callback.ErrorCode != "" || !callback.Code.Present() || len(callback.Code.Reveal()) > 16384 {
		return false
	}
	if flow.Expires <= now.Unix() || flow.Expires > now.Add(10*time.Minute).Unix() || len(flow.Verifier) != 43 || len(flow.Nonce) != 43 {
		return false
	}
	return len(flow.State) >= 32 && subtle.ConstantTimeCompare([]byte(flow.State), []byte(callback.State.Reveal())) == 1
}

func (c *Client) Refresh(ctx context.Context, refresh secret.Value, tasks bool) (application.Tokens, error) {
	if !refresh.Present() {
		return application.Tokens{}, failure("Authentication")
	}
	// MSAL added these OIDC scopes automatically in the Python implementation.
	// email requires openid; offline_access preserves refresh-token rotation.
	scope := "openid profile offline_access User.Read Mail.Read email"
	if tasks {
		scope = "openid profile offline_access User.Read Tasks.ReadWrite"
	}
	response, err := c.exchange(ctx, url.Values{"grant_type": {"refresh_token"}, "refresh_token": {refresh.Reveal()}, "scope": {scope}})
	if err != nil {
		return application.Tokens{}, err
	}
	return c.tokens(response, scope)
}

func (c *Client) exchange(ctx context.Context, form url.Values) (tokenResponse, error) {
	form.Set("client_id", c.config.ClientID)
	form.Set("redirect_uri", c.config.RedirectURI)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, authority+c.config.Tenant+"/oauth2/v2.0/token", strings.NewReader(form.Encode()))
	if err != nil {
		return tokenResponse{}, failure("PermanentProvider")
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	// Authorization codes are single-use; transport failures are not blindly retried.
	data, err := c.request(req, 1)
	if err != nil {
		return tokenResponse{}, err
	}
	var response tokenResponse
	if json.Unmarshal(data, &response) != nil {
		return response, failure("InvalidResponse")
	}
	return response, nil
}

func (c *Client) tokens(response tokenResponse, requested string) (application.Tokens, error) {
	if response.Access == "" || !strings.EqualFold(response.Type, "Bearer") || response.Expires <= 0 || response.Expires > 86400 {
		return application.Tokens{}, failure("InvalidResponse")
	}
	scope := response.Scope
	if scope == "" {
		scope = requested
	}
	return application.Tokens{AccessToken: secret.New(response.Access), RefreshToken: secret.New(response.Refresh), ExpiresAt: c.clock.Now().Add(time.Duration(response.Expires) * time.Second), Capabilities: scopes(scope)}, nil
}
