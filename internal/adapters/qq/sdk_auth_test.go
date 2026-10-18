package qq

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/tencent-connect/botgo"
	"github.com/tencent-connect/botgo/dto"
	"github.com/tencent-connect/botgo/openapi/options"
	"golang.org/x/oauth2"
)

func TestBotgoAuthorizationScheme(t *testing.T) {
	InstallSafeSDKLogger(slog.New(slog.NewTextHandler(io.Discard, nil)))
	InstallSDKProtocolFilter()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "QQBot synthetic-token" {
			t.Error("SDK emitted incorrect authentication scheme")
		}
		if r.Header.Get("X-Union-Appid") != "synthetic-app" {
			t.Error("SDK omitted application identity")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"synthetic-receipt"}`))
	}))
	defer server.Close()
	source := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: "synthetic-token", TokenType: "QQBot"})
	api := botgo.NewOpenAPI("synthetic-app", source).SetDebug(false)
	result, err := api.PostC2CMessage(context.Background(), "synthetic-owner", dto.MessageToCreate{Content: "synthetic-message"}, options.WithURL(server.URL))
	if err != nil || result.ID != "synthetic-receipt" {
		t.Fatal("SDK request mapping failed")
	}
}

func TestAuthProtocolFilterFailsClosedWithoutIdentity(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "https://api.sgroup.qq.com/gateway/bot", nil)
	if qqBotAuthScheme(req, nil) == nil {
		t.Fatal("missing application identity accepted")
	}
	req.Header.Set("X-Union-Appid", "synthetic-app")
	if qqBotAuthScheme(req, nil) == nil {
		t.Fatal("missing authorization accepted")
	}
	for _, scheme := range []string{"Bearer", "QQBot"} {
		req.Header.Set("Authorization", scheme+" synthetic-token")
		if qqBotAuthScheme(req, nil) != nil || req.Header.Get("Authorization") != "QQBot synthetic-token" {
			t.Fatal("incorrect protocol normalization")
		}
	}
}
