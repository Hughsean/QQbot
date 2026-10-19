package microsoft

import (
	"context"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/ids"
)

type identityClaims struct {
	Tenant    string `json:"tid"`
	NotBefore int64  `json:"nbf"`
	Version   string `json:"ver"`
}

func (c *Client) verifyIDToken(ctx context.Context, raw, nonce string) error {
	// The untrusted tenant is used only to select a fixed Microsoft issuer.
	// Signature verification must succeed before any claims become identity.
	tenant, err := untrustedTenant(raw)
	if err != nil || !c.acceptsTenant(tenant) {
		return failure("Authentication")
	}
	issuer := authority + tenant + "/v2.0"
	var keyFailure error
	verifier := oidc.NewVerifier(issuer, scopedKeySet{client: c, issuer: issuer, failure: &keyFailure}, &oidc.Config{ClientID: c.config.ClientID, SupportedSigningAlgs: []string{"RS256"}, Now: c.clock.Now})
	token, err := verifier.Verify(ctx, raw)
	if err != nil {
		return signatureFailure(keyFailure)
	}
	var claims identityClaims
	if token.Claims(&claims) != nil || claims.Tenant != tenant || claims.Version != "2.0" {
		return failure("Authentication")
	}
	if token.Subject == "" || subtle.ConstantTimeCompare([]byte(token.Nonce), []byte(nonce)) != 1 {
		return failure("Authentication")
	}
	if !validTokenTime(token, c.clock.Now(), claims.NotBefore) {
		return failure("Authentication")
	}
	return nil
}

func signatureFailure(err error) error {
	var provider contracts.ProviderError
	if errors.As(err, &provider) {
		return provider
	}
	return failure("Authentication")
}

func validTokenTime(token *oidc.IDToken, now time.Time, notBefore int64) bool {
	return token.Expiry.After(now) && token.IssuedAt.Unix() > 0 && token.Expiry.After(token.IssuedAt) && !token.IssuedAt.After(now.Add(time.Minute)) && notBefore > 0 && !time.Unix(notBefore, 0).After(now.Add(time.Minute))
}

func untrustedTenant(raw string) (string, error) {
	parts := strings.Split(raw, ".")
	if len(parts) != 3 || len(raw) > 65536 {
		return "", failure("Authentication")
	}
	data, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return "", failure("Authentication")
	}
	var claims identityClaims
	if json.Unmarshal(data, &claims) != nil || ids.Validate(claims.Tenant) != nil {
		return "", failure("Authentication")
	}
	return claims.Tenant, nil
}

func (c *Client) acceptsTenant(tenant string) bool {
	switch c.config.Tenant {
	case "common":
		return true
	case "consumers":
		return tenant == consumerTenant
	case "organizations":
		return tenant != consumerTenant
	default:
		return tenant == c.config.Tenant
	}
}
