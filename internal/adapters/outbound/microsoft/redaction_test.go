package microsoft

import (
	"bytes"
	"fmt"
	"log/slog"
	"strings"
	"testing"
)

func TestOAuthDTOsRedactLogsAndFormatting(t *testing.T) {
	flow := flowState{State: "synthetic-private", Verifier: "synthetic-private", Nonce: "synthetic-private"}
	tokens := tokenResponse{Access: "synthetic-private", Refresh: "synthetic-private", ID: "synthetic-private"}
	if strings.Contains(fmt.Sprintf("%+v %#v %+v %#v", flow, flow, tokens, tokens), "synthetic-private") {
		t.Fatal("OAuth DTO formatted secrets")
	}
	var buffer bytes.Buffer
	slog.New(slog.NewJSONHandler(&buffer, nil)).Info("oauth", "flow", flow, "tokens", tokens)
	if strings.Contains(buffer.String(), "synthetic-private") {
		t.Fatal("OAuth DTO logged secrets")
	}
}
