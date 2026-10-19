package infrastructure

import "testing"

func TestConnectionLockKeyMatchesPythonLow63BitMapping(t *testing.T) {
	for _, input := range []struct {
		id   string
		want int64
	}{
		{"00000000-0000-4000-0000-000000000001", 1},
		{"00000000-0000-4000-4000-000000000000", -4611686018427387904},
		{"00000000-0000-4000-7fff-ffffffffffff", -1},
		{"00000000-0000-4000-8000-000000000001", 1},
		{"00000000-0000-4000-ffff-ffffffffffff", -1},
	} {
		if got := lockKey(input.id); got != input.want {
			t.Fatalf("connection lock changed: %d != %d", got, input.want)
		}
	}
}

func TestSourceReferencesAndSenderMasksMatchLegacy(t *testing.T) {
	for _, input := range []struct{ kind, prefix string }{{"MICROSOFT_MAIL", "mail"}, {"QQ_MAIL", "qq-mail"}, {"QQ_DIRECT", "qq"}, {"QQ_FORWARD", "qq-forward"}, {"OWNER_NOTE", "owner-note"}} {
		if got := sourceRef(input.kind, "connection", "external"); got != input.prefix+":connection:external" {
			t.Fatal("source identity changed")
		}
	}
	for _, input := range []struct{ sender, mask string }{{"sender@example.test", "s***@example.test"}, {"会@example.test", "会***@example.test"}, {"@example.test", "***@example.test"}, {"openid", "sender"}} {
		if got := maskSender(input.sender); got != input.mask {
			t.Fatal("sender mask changed")
		}
	}
}
