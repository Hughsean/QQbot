package contracts

import (
	"bytes"
	"fmt"
	"log/slog"
	"strings"
	"testing"
)

func TestSourceContentRedactedInFormattingAndStructuredLogs(t *testing.T) {
	input := Input{BodyText: "synthetic-private", BodyHTML: "synthetic-private", SourceRef: "synthetic-private"}
	content := Content{Subject: "synthetic-private", Body: "synthetic-private"}
	var output bytes.Buffer
	slog.New(slog.NewJSONHandler(&output, nil)).Info("test", "input", input, "content", content)
	text := fmt.Sprintf("%s %v %#v %s %v %#v", input, input, input, content, content, content) + output.String()
	if strings.Contains(text, "synthetic-private") || !strings.Contains(text, "REDACTED") {
		t.Fatal("source content leaked to logs")
	}
}
