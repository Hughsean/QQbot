package microsoft

import (
	"context"
	"net/http"
	"slices"
	"strings"
	"testing"

	"qqtimeagent/internal/platform/secret"
)

func TestRefreshPreservesOIDCDependenciesAndNarrowsGraphPermissions(t *testing.T) {
	c, _ := testClient(t)
	refresh := secret.New("synthetic-original")
	for _, tasks := range []bool{false, true} {
		c.http.Transport = transport(func(r *http.Request) (*http.Response, error) {
			if err := r.ParseForm(); err != nil {
				t.Fatal(err)
			}
			scopes := strings.Fields(r.Form.Get("scope"))
			if slices.Contains(scopes, "email") && !slices.Contains(scopes, "openid") {
				return response(400, `{"error":"invalid_scope"}`), nil
			}
			for _, required := range []string{"openid", "profile", "offline_access", "User.Read"} {
				if !slices.Contains(scopes, required) {
					t.Fatalf("missing refresh scope %s", required)
				}
			}
			if r.Form.Get("refresh_token") != refresh.Reveal() || r.Form.Has("client_secret") {
				t.Fatal("refresh rotation or public-client boundary changed")
			}
			graphScope := "User.Read Mail.Read"
			if tasks {
				graphScope = "User.Read Tasks.ReadWrite"
			}
			if !slices.Equal(canonicalCapabilities(scopes), strings.Fields(graphScope)) {
				t.Fatal("refresh request expanded Graph permissions")
			}
			return response(200, `{"access_token":"synthetic-access","refresh_token":"synthetic-rotated","token_type":"Bearer","expires_in":3600,"scope":"`+graphScope+`"}`), nil
		})
		tokens, err := c.Refresh(context.Background(), refresh, tasks)
		if err != nil || tokens.RefreshToken.Reveal() != "synthetic-rotated" || len(tokens.Capabilities) != 2 {
			t.Fatal("refresh did not rotate token or normalize capabilities", err)
		}
		refresh = tokens.RefreshToken
	}
}

func canonicalCapabilities(scopes []string) []string {
	var result []string
	for _, scope := range scopes {
		switch scope {
		case "openid", "profile", "offline_access", "email":
		default:
			result = append(result, scope)
		}
	}
	return result
}
