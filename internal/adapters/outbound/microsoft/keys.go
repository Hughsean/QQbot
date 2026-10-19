package microsoft

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"github.com/go-jose/go-jose/v4"
)

// Microsoft's common key set includes issuer-scoped keys. Checking only the JWT
// issuer is insufficient: the signing key must also authorize that tenant.
type scopedKey struct {
	key    jose.JSONWebKey
	issuer string
}
type keyCache struct {
	mutex   sync.Mutex
	values  []scopedKey
	expires time.Time
}
type scopedKeySet struct {
	client  *Client
	issuer  string
	failure *error
}

func (s scopedKeySet) VerifySignature(ctx context.Context, raw string) (payload []byte, err error) {
	defer func() {
		if s.failure != nil && err != nil {
			*s.failure = err
		}
	}()
	signed, err := jose.ParseSigned(raw, []jose.SignatureAlgorithm{jose.RS256})
	if err != nil || len(signed.Signatures) != 1 {
		return nil, failure("Authentication")
	}
	kid := signed.Signatures[0].Header.KeyID
	if kid == "" {
		return nil, failure("Authentication")
	}
	for attempt := 0; attempt < 2; attempt++ {
		keys, err := s.client.loadKeys(ctx, attempt == 1)
		if err != nil {
			return nil, err
		}
		if payload, ok := verifyWithKeys(signed, keys, kid, s.issuer); ok {
			return payload, nil
		}
	}
	return nil, failure("Authentication")
}

func verifyWithKeys(signed *jose.JSONWebSignature, keys []scopedKey, kid, issuer string) ([]byte, bool) {
	for _, key := range keys {
		if key.key.KeyID != kid || !allowedKey(key, issuer) {
			continue
		}
		if payload, err := signed.Verify(key.key.Key); err == nil {
			return payload, true
		}
	}
	return nil, false
}

func allowedKey(key scopedKey, issuer string) bool {
	if key.issuer != issuer && key.issuer != authority+"{tenantid}/v2.0" {
		return false
	}
	return key.key.Valid() && key.key.IsPublic() && key.key.Use == "sig" && (key.key.Algorithm == "" || key.key.Algorithm == "RS256")
}

func (c *Client) loadKeys(ctx context.Context, force bool) ([]scopedKey, error) {
	c.keys.mutex.Lock()
	defer c.keys.mutex.Unlock()
	if !force && len(c.keys.values) > 0 && c.clock.Now().Before(c.keys.expires) {
		return c.keys.values, nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, authority+"common/discovery/v2.0/keys", nil)
	if err != nil {
		return nil, failure("PermanentProvider")
	}
	data, err := c.request(req, 2)
	if err != nil {
		return nil, err
	}
	keys, err := decodeKeys(data)
	if err != nil {
		return nil, err
	}
	c.keys.values, c.keys.expires = keys, c.clock.Now().Add(30*time.Minute)
	return keys, nil
}

func decodeKeys(data []byte) ([]scopedKey, error) {
	var document struct {
		Keys []json.RawMessage `json:"keys"`
	}
	if json.Unmarshal(data, &document) != nil || len(document.Keys) == 0 || len(document.Keys) > 100 {
		return nil, failure("InvalidResponse")
	}
	keys := make([]scopedKey, 0, len(document.Keys))
	for _, raw := range document.Keys {
		var key jose.JSONWebKey
		var metadata struct {
			Issuer string `json:"issuer"`
		}
		if json.Unmarshal(raw, &key) != nil || json.Unmarshal(raw, &metadata) != nil {
			return nil, failure("InvalidResponse")
		}
		keys = append(keys, scopedKey{key: key, issuer: metadata.Issuer})
	}
	return keys, nil
}
