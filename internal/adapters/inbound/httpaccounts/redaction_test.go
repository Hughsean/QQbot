package httpaccounts

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestConnectDTOFormattingRedactsSubmittedCredential(t *testing.T) {
	value := connectRequest{Address: "123@qq.com", Code: "synthetic-private-code"}
	if strings.Contains(fmt.Sprintf("%+v %#v", value, value), "synthetic-private") {
		t.Fatal("connect DTO formatted secrets")
	}
	var buffer bytes.Buffer
	slog.New(slog.NewJSONHandler(&buffer, nil)).Info("connect", "request", value)
	if strings.Contains(buffer.String(), "synthetic-private") || strings.Contains(buffer.String(), "123@qq.com") {
		t.Fatal("connect DTO logged secrets")
	}
}

func TestValidSignedNonOwnerReturnsForbidden(t *testing.T) {
	f := setup(t)
	payload := struct {
		Subject string `json:"sub"`
		Expires int64  `json:"exp"`
		ID      string `json:"jti"`
	}{Subject: "other", Expires: (fixedClock{}).Now().Add(time.Minute).Unix(), ID: "synthetic-session-id"}
	data, _ := json.Marshal(payload)
	encoded := base64.RawURLEncoding.EncodeToString(data)
	mac := hmac.New(sha256.New, []byte(strings.Repeat("k", 32)))
	_, _ = mac.Write([]byte(encoded))
	token := encoded + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	for _, path := range []string{"/api/v1/connections/microsoft", "/api/v1/connections/qq-mail", "/oauth/microsoft/start", "/qq-mail/connect"} {
		r := f.request("GET", path, "", false, false)
		r.AddCookie(&http.Cookie{Name: ownerCookie, Value: token})
		if w := f.serve(r); w.Code != 403 {
			t.Fatal("valid non-owner identity accepted or wrong status", path, w.Code)
		}
	}
}
