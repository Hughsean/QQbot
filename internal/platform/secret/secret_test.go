package secret

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"testing"
)

func TestSecretNeverFormatsOrSerializes(t *testing.T) {
	v := New("synthetic-sensitive-value")
	data, err := json.Marshal(struct{ Key Value }{v})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	slog.New(slog.NewJSONHandler(&logs, nil)).Info("config", "key", v)
	for _, output := range []string{fmt.Sprint(v), fmt.Sprintf("%#v", v), string(data), logs.String()} {
		if strings.Contains(output, v.Reveal()) || !strings.Contains(output, "[REDACTED]") {
			t.Fatalf("unsafe secret formatting: %s", output)
		}
	}
	if !v.Present() || New("").Present() {
		t.Fatal("incorrect presence")
	}
	text, _ := v.MarshalText()
	if string(text) != "[REDACTED]" {
		t.Fatal("unsafe text serialization")
	}
}
