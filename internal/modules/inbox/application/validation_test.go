package application

import (
	"strings"
	"testing"

	"qqtimeagent/internal/modules/inbox/contracts"
)

func TestMailMetadataValidationRejectsMalformedOrUnboundedInput(t *testing.T) {
	negative := int64(-1)
	for _, mutate := range []func(*contracts.MailChange){
		func(c *contracts.MailChange) { c.Body = "nul\x00body" },
		func(c *contracts.MailChange) { c.Subject = string([]byte{0xff}) },
		func(c *contracts.MailChange) { c.InternetMessageID = strings.Repeat("x", 999) },
		func(c *contracts.MailChange) { c.ChangeKey = strings.Repeat("x", 513) },
		func(c *contracts.MailChange) { c.Recipients = []contracts.Address{{Address: " "}} },
		func(c *contracts.MailChange) { c.Recipients = []contracts.Address{{Address: strings.Repeat("x", 321)}} },
		func(c *contracts.MailChange) {
			c.Recipients = []contracts.Address{{Address: "a@example.test", DisplayName: strings.Repeat("x", 321)}}
		},
		func(c *contracts.MailChange) {
			c.Attachments = []contracts.AttachmentMetadata{{DeclaredSize: &negative}}
		},
		func(c *contracts.MailChange) {
			c.Attachments = []contracts.AttachmentMetadata{{Filename: strings.Repeat("x", 1025)}}
		},
		func(c *contracts.MailChange) {
			c.Attachments = []contracts.AttachmentMetadata{{ContentType: strings.Repeat("x", 256)}}
		},
	} {
		change := mail()
		mutate(&change)
		if _, err := rawMail(change); err == nil {
			t.Fatal("malformed mail persisted")
		}
	}
	change := mail()
	change.Recipients = []contracts.Address{{Address: "a@example.test", DisplayName: "Name"}}
	change.Attachments = []contracts.AttachmentMetadata{{ContentType: "text/plain"}}
	if _, err := rawMail(change); err != nil {
		t.Fatal("valid typed metadata rejected", err)
	}
}
