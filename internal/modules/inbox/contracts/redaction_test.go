package contracts

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"testing"
)

func TestMailContentFormattingAndStructuredLoggingAreRedacted(t *testing.T) {
	mail := MailChange{Body: "synthetic-private"}
	raw := RawContent{BodyHTML: "synthetic-private"}
	content := ContentView{BodyText: "synthetic-private"}
	var output bytes.Buffer
	slog.New(slog.NewJSONHandler(&output, nil)).Info("test", "mail", mail, "raw", raw, "content", content)
	text := fmt.Sprintf("%s %v %#v %s %v %#v %s %v %#v", mail, mail, mail, raw, raw, raw, content, content, content) + output.String()
	if strings.Contains(text, "synthetic-private") || !strings.Contains(text, "REDACTED") {
		t.Fatal("source content leaked")
	}
}

func TestMailMetadataJSONKeepsNullableLegacyFields(t *testing.T) {
	for _, input := range []struct {
		value Address
		want  string
	}{{Address{Address: "a@example.test"}, `{"address":"a@example.test","display_name":null}`}, {Address{Address: "a@example.test", DisplayName: "Name"}, `{"address":"a@example.test","display_name":"Name"}`}} {
		data, err := json.Marshal(input.value)
		if err != nil || string(data) != input.want {
			t.Fatal("recipient JSON changed")
		}
	}
	data, err := json.Marshal(AttachmentMetadata{ContentType: "application/pdf"})
	if err != nil || string(data) != `{"filename":null,"content_type":"application/pdf","declared_size":null}` {
		t.Fatal("nullable attachment JSON changed")
	}
}
