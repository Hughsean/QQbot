package qqmail

import (
	"bytes"
	"context"
	"crypto/tls"
	"errors"
	"net"
	"strings"
	"testing"
	"time"

	"qqtimeagent/internal/platform/secret"
)

type fixedClock struct{ now time.Time }

func (c fixedClock) Now() time.Time { return c.now }

type connection struct {
	input                 *bytes.Buffer
	output                bytes.Buffer
	closed                bool
	writeErr, deadlineErr error
	deadline              time.Time
}

func (c *connection) Read(p []byte) (int, error) { return c.input.Read(p) }
func (c *connection) Write(p []byte) (int, error) {
	if c.writeErr != nil {
		return 0, c.writeErr
	}
	return c.output.Write(p)
}
func (c *connection) Close() error                   { c.closed = true; return nil }
func (*connection) LocalAddr() net.Addr              { return &net.TCPAddr{} }
func (*connection) RemoteAddr() net.Addr             { return &net.TCPAddr{} }
func (c *connection) SetDeadline(t time.Time) error  { c.deadline = t; return c.deadlineErr }
func (*connection) SetReadDeadline(time.Time) error  { return nil }
func (*connection) SetWriteDeadline(time.Time) error { return nil }

type dial func(context.Context, string, string) (net.Conn, error)

func (d dial) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	return d(ctx, network, address)
}

func TestFixedTLSAndReadOnlyCommands(t *testing.T) {
	now := time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)
	v, err := New(fixedClock{now})
	if err != nil {
		t.Fatal(err)
	}
	config := v.dialer.(*tls.Dialer).Config
	if config.ServerName != "imap.qq.com" || config.InsecureSkipVerify || config.MinVersion < tls.VersionTLS12 {
		t.Fatal("TLS verification weakened")
	}
	c := &connection{input: bytes.NewBufferString("* OK ready\r\n* CAPABILITY IMAP4rev1\r\nA1 OK logged in\r\n* 2 EXISTS\r\n* FLAGS (\\Seen)\r\nA2 OK [READ-ONLY] examined\r\n")}
	v.dialer = dial(func(ctx context.Context, network, address string) (net.Conn, error) {
		if network != "tcp" || address != "imap.qq.com:993" {
			t.Fatal("arbitrary IMAP endpoint")
		}
		if _, ok := ctx.Deadline(); !ok {
			t.Fatal("unbounded dial")
		}
		return c, nil
	})
	if err := v.Verify(context.Background(), secret.New("123@qq.com"), secret.New(`synthetic\"code`)); err != nil {
		t.Fatal(err)
	}
	if !c.closed || !c.deadline.Equal(now.Add(15*time.Second)) {
		t.Fatal("connection not bounded/closed")
	}
	if c.output.String() != `A1 LOGIN "123@qq.com" "synthetic\\\"code"`+"\r\nA2 EXAMINE INBOX\r\n" {
		t.Fatal("unexpected or unsafe IMAP commands")
	}
	if _, err := New(nil); err == nil {
		t.Fatal("missing clock accepted")
	}
}

func TestIMAPRefusesInjectionMalformedAndUnboundedReplies(t *testing.T) {
	v, _ := New(fixedClock{time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)})
	for _, value := range []string{"", "x\r\nA2 STORE 1 FLAGS (\\Deleted)", "x\x00", strings.Repeat("x", 4097)} {
		if err := v.Verify(context.Background(), secret.New("123@qq.com"), secret.New(value)); err == nil {
			t.Fatal("unsafe credential accepted")
		}
	}
	for _, input := range []string{"", "* BYE synthetic-private\r\n", "* OK ready\n", "* OK " + strings.Repeat("x", 65536) + "\r\n", "* OK ready\r\nA1 NO synthetic-private\r\n", "* OK ready\r\nA1 BAD synthetic-private\r\n", "* OK ready\r\n" + strings.Repeat("* CAPABILITY synthetic\r\n", 129), "* OK ready\r\nA1 OK login\r\nA2 NO synthetic-private\r\n"} {
		c := &connection{input: bytes.NewBufferString(input)}
		v.dialer = dial(func(context.Context, string, string) (net.Conn, error) { return c, nil })
		if err := v.Verify(context.Background(), secret.New("123@qq.com"), secret.New("synthetic-private")); err == nil || strings.Contains(err.Error(), "synthetic-private") {
			t.Fatal("malformed response accepted or error leaked", err)
		}
		if !c.closed {
			t.Fatal("failed connection not closed")
		}
	}
	for _, mode := range []string{"dial", "deadline", "write"} {
		c := &connection{input: bytes.NewBufferString("* OK ready\r\n")}
		if mode == "deadline" {
			c.deadlineErr = errors.New("synthetic-private")
		}
		if mode == "write" {
			c.writeErr = errors.New("synthetic-private")
		}
		v.dialer = dial(func(context.Context, string, string) (net.Conn, error) {
			if mode == "dial" {
				return nil, errors.New("synthetic-private")
			}
			return c, nil
		})
		if err := v.Verify(context.Background(), secret.New("123@qq.com"), secret.New("synthetic-private")); err == nil || strings.Contains(err.Error(), "synthetic-private") {
			t.Fatal("transport failure not sanitized")
		}
	}
}
