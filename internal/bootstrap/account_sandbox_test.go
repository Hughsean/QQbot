package bootstrap

import (
	"context"
	"testing"

	"qqtimeagent/internal/platform/secret"
)

func TestAccountSandboxRequiresExplicitCommandFlagAndConfiguration(t *testing.T) {
	for _, role := range []string{"microsoft-sandbox", "qq-mail-sandbox"} {
		for _, args := range [][]string{{role}, {role, "wrong"}} {
			if _, err := parseRole(args); err == nil {
				t.Fatal("account probe did not require explicit flag")
			}
		}
		if parsed, err := parseRole([]string{role, "--allow-account-read"}); err != nil || parsed != role {
			t.Fatal("account probe command rejected")
		}
	}
	for _, cfg := range []Config{{Container: true, ListenPort: 8000}, {ListenPort: 8123}, {ListenPort: 8000}} {
		if err := runMicrosoftSandbox(context.Background(), cfg); err == nil {
			t.Fatal("invalid Microsoft probe configuration accepted")
		}
	}
	if err := runMailSandbox(context.Background(), Config{}); err == nil {
		t.Fatal("mail sandbox missing credentials accepted")
	}
	if err := runMailSandbox(context.Background(), Config{MailSandbox: MailSandboxConfig{Address: secret.New("123@qq.com")}}); err == nil {
		t.Fatal("missing authorization code accepted")
	}
	for _, role := range []string{"microsoft-sandbox", "qq-mail-sandbox"} {
		if handled, err := runSandbox(context.Background(), Config{}, role); !handled || err == nil {
			t.Fatal("probe role not routed")
		}
	}
	c, err := ParseConfig(map[string]string{"MICROSOFT_CLIENT_ID": "synthetic-id", "MICROSOFT_TENANT": "common", "QQ_MAIL_BOOTSTRAP_ADDRESS": "123@qq.com", "QQ_MAIL_BOOTSTRAP_AUTH_CODE": "synthetic-code"})
	if err != nil || !c.Microsoft.ClientID.Present() || !c.MailSandbox.Code.Present() {
		t.Fatal("sandbox configuration not read through Bootstrap")
	}
}
