package microsoft

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"

	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/platform/secret"
)

const bodyLimit = 1 << 20

func (c *Client) request(req *http.Request, attempts int) ([]byte, error) {
	ctx, cancel := context.WithTimeout(req.Context(), 20*time.Second)
	defer cancel()
	for range attempts {
		response, err := c.http.Do(req.Clone(ctx))
		if err != nil {
			if ctx.Err() != nil {
				return nil, failure("TransientProvider")
			}
			continue
		}
		data, readErr := io.ReadAll(io.LimitReader(response.Body, bodyLimit+1))
		_ = response.Body.Close()
		if readErr != nil || len(data) > bodyLimit {
			return nil, failure("InvalidResponse")
		}
		if response.StatusCode >= 200 && response.StatusCode < 300 {
			return data, nil
		}
		class := classify(response.StatusCode, data)
		if class != "TransientProvider" {
			return nil, failure(class)
		}
	}
	return nil, failure("TransientProvider")
}

func classify(status int, data []byte) string {
	if status == http.StatusTooManyRequests {
		return "RateLimit"
	}
	if status >= 500 {
		return "TransientProvider"
	}
	if status == http.StatusUnauthorized {
		return "Authentication"
	}
	if status == http.StatusForbidden {
		return "Permission"
	}
	var payload struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(data, &payload) == nil && payload.Error == "invalid_grant" {
		return "Authentication"
	}
	return "PermanentProvider"
}

func (c *Client) Profile(ctx context.Context, token secret.Value) (application.Profile, error) {
	if !token.Present() {
		return application.Profile{}, failure("Authentication")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, graph, nil)
	if err != nil {
		return application.Profile{}, failure("PermanentProvider")
	}
	req.Header.Set("Authorization", "Bearer "+token.Reveal())
	data, err := c.request(req, 2)
	if err != nil {
		return application.Profile{}, err
	}
	var profile struct {
		ID        string `json:"id"`
		Mail      string `json:"mail"`
		Principal string `json:"userPrincipalName"`
	}
	if json.Unmarshal(data, &profile) != nil || strings.TrimSpace(profile.ID) == "" {
		return application.Profile{}, failure("InvalidResponse")
	}
	if profile.Mail == "" {
		profile.Mail = profile.Principal
	}
	return application.Profile{AccountID: secret.New(profile.ID), Email: secret.New(profile.Mail)}, nil
}
