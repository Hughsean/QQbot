package microsoft

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"testing"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/secret"
)

func TestDiagnosticsAllowOnlyFixedProtocolCodes(t *testing.T) {
	for _, input := range []struct{ body, code string }{
		{`{"error":"invalid_scope","error_description":"synthetic-private"}`, "invalid_scope"},
		{`{"error":{"code":"BadRequest","message":"synthetic-private"}}`, "BadRequest"},
		{`{"error":"synthetic-private"}`, "unknown"},
		{`{"error":{"code":"synthetic-private"}}`, "unknown"},
		{`{"error":123}`, "unknown"}, {`invalid`, "unknown"}, {`{}`, "unknown"},
	} {
		if code := safeProviderCode([]byte(input.body)); code != input.code {
			t.Fatalf("unexpected diagnostic code %q", code)
		}
	}
}

func TestRejectedRequestLogsStatusWithoutSecrets(t *testing.T) {
	c, _ := testClient(t)
	var output bytes.Buffer
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&output, nil)))
	t.Cleanup(func() { slog.SetDefault(previous) })
	c.http.Transport = transport(func(*http.Request) (*http.Response, error) {
		return response(400, `{"error":"invalid_scope","error_description":"synthetic-private"}`), nil
	})
	_, err := c.Refresh(context.Background(), secret.New("synthetic-private"), false)
	var provider contracts.ProviderError
	if !errors.As(err, &provider) || provider.Class != "PermanentProvider" {
		t.Fatal("diagnostics changed provider classification")
	}
	log := output.String()
	if !strings.Contains(log, "status=400") || !strings.Contains(log, "code=invalid_scope") || strings.Contains(log, "synthetic-private") || strings.Contains(log, "http") {
		t.Fatal("diagnostic omitted status/code or leaked request data")
	}
}
