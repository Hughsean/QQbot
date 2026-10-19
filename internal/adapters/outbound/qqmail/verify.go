// Package qqmail verifies password-equivalent IMAP credentials over fixed TLS.
package qqmail

import (
	"bufio"
	"context"
	"crypto/tls"
	"net"
	"strings"
	"time"

	"qqtimeagent/internal/modules/connections/application"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/secret"
)

type dialer interface {
	DialContext(context.Context, string, string) (net.Conn, error)
}
type Verifier struct {
	clock  clock.Clock
	dialer dialer
}

func New(timeSource clock.Clock) (*Verifier, error) {
	if timeSource == nil {
		return nil, application.ProviderError{Class: "Configuration"}
	}
	return &Verifier{clock: timeSource, dialer: &tls.Dialer{NetDialer: &net.Dialer{Timeout: 10 * time.Second}, Config: &tls.Config{ServerName: "imap.qq.com", MinVersion: tls.VersionTLS12}}}, nil
}

func (v *Verifier) Verify(ctx context.Context, address, code secret.Value) error {
	if !safeValue(address.Reveal()) || !safeValue(code.Reveal()) {
		return application.ProviderError{Class: "Authentication"}
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	conn, err := v.dialer.DialContext(ctx, "tcp", "imap.qq.com:993")
	if err != nil {
		return application.ProviderError{Class: "TransientProvider"}
	}
	defer func() { _ = conn.Close() }()
	stop := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer stop()
	if err := conn.SetDeadline(v.clock.Now().Add(15 * time.Second)); err != nil {
		return application.ProviderError{Class: "TransientProvider"}
	}
	reader := bufio.NewReaderSize(conn, 64*1024)
	greeting, err := line(reader)
	if err != nil {
		return err
	}
	if !strings.HasPrefix(greeting, "* OK ") {
		return application.ProviderError{Class: "InvalidResponse"}
	}
	if err := command(conn, reader, "A1", "LOGIN "+quote(address.Reveal())+" "+quote(code.Reveal())); err != nil {
		return err
	}
	// EXAMINE is read-only. No SELECT, STORE, deletion, or message fetch occurs.
	return command(conn, reader, "A2", "EXAMINE INBOX")
}

func safeValue(value string) bool {
	return value != "" && len(value) <= 4096 && !strings.ContainsAny(value, "\r\n\x00")
}
func quote(value string) string {
	return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(value) + `"`
}

func line(reader *bufio.Reader) (string, error) {
	data, err := reader.ReadSlice('\n')
	if err != nil {
		return "", application.ProviderError{Class: "TransientProvider"}
	}
	if len(data) < 2 || data[len(data)-2] != '\r' {
		return "", application.ProviderError{Class: "InvalidResponse"}
	}
	return string(data[:len(data)-2]), nil
}

func command(conn net.Conn, reader *bufio.Reader, tag, verb string) error {
	if _, err := conn.Write([]byte(tag + " " + verb + "\r\n")); err != nil {
		return application.ProviderError{Class: "TransientProvider"}
	}
	for range 128 {
		value, err := line(reader)
		if err != nil {
			return err
		}
		if strings.HasPrefix(value, tag+" OK ") {
			return nil
		}
		if strings.HasPrefix(value, tag+" NO ") {
			return application.ProviderError{Class: "Authentication"}
		}
		if !strings.HasPrefix(value, "* ") {
			return application.ProviderError{Class: "InvalidResponse"}
		}
	}
	return application.ProviderError{Class: "InvalidResponse"}
}

var _ application.MailVerifier = (*Verifier)(nil)
