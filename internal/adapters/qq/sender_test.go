package qq

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"

	"github.com/tencent-connect/botgo/dto"
	"github.com/tencent-connect/botgo/openapi/options"

	"qqtimeagent/internal/modules/notifications/contracts"
	"qqtimeagent/internal/platform/secret"
)

type fakeAPI struct {
	called  int
	owner   string
	message dto.MessageToCreate
	result  *dto.Message
	err     error
}

func (f *fakeAPI) PostC2CMessage(_ context.Context, owner string, msg dto.APIMessage, _ ...options.Option) (*dto.Message, error) {
	f.called++
	f.owner = owner
	f.message = msg.(dto.MessageToCreate)
	return f.result, f.err
}

func TestSenderTargetsOnlyOwnerAndPreservesReplyDedup(t *testing.T) {
	f := &fakeAPI{result: &dto.Message{ID: "synthetic-receipt"}}
	s := Sender{API: f, Owner: secret.New("synthetic-owner")}
	id, err := s.Send(context.Background(), contracts.Message{Content: "提醒", ReplyTo: "synthetic-inbound", Sequence: 3})
	if err != nil || id != "synthetic-receipt" || f.owner != "synthetic-owner" || f.message.MsgSeq != 3 || f.message.MsgID != "synthetic-inbound" {
		t.Fatal("invalid send mapping")
	}
	if _, err := s.Send(context.Background(), contracts.Message{Content: "提醒"}); err != nil {
		t.Fatal(err)
	}
	if f.message.MsgID != "" {
		t.Fatal("active send reused reply identity")
	}
}

func TestSenderDoesNotRetryAmbiguousOutcomesOrLeakErrors(t *testing.T) {
	f := &fakeAPI{err: errors.New("synthetic-sensitive-token")}
	s := Sender{API: f, Owner: secret.New("synthetic-owner")}
	_, err := s.Send(context.Background(), contracts.Message{Content: "提醒"})
	if !errors.Is(err, ErrAmbiguousDelivery) || f.called != 1 || strings.Contains(err.Error(), "synthetic-sensitive-token") {
		t.Fatal("unsafe retry or error")
	}
	for _, msg := range []contracts.Message{{}, {Content: "提醒", ReplyTo: "x"}} {
		if _, err := s.Send(context.Background(), msg); err == nil {
			t.Fatal("invalid send accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := s.Send(ctx, contracts.Message{Content: "提醒"}); err == nil || f.called != 1 {
		t.Fatal("cancelled send reached provider")
	}
	f.err = nil
	if _, err := s.Send(context.Background(), contracts.Message{Content: "提醒"}); !errors.Is(err, ErrAmbiguousDelivery) {
		t.Fatal("missing receipt treated as success")
	}
}

func TestSDKLoggingDropsAllRawArguments(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&output, nil))
	l := safeLogger{logger}
	l.Debug("synthetic-sensitive")
	l.Debugf("%s", "synthetic-sensitive")
	l.Info("synthetic-sensitive")
	l.Infof("%s", "synthetic-sensitive")
	l.Warn("synthetic-sensitive")
	l.Warnf("%s", "synthetic-sensitive")
	l.Error("synthetic-sensitive")
	l.Errorf("%s", "synthetic-sensitive")
	if l.Sync() != nil || strings.Contains(output.String(), "synthetic-sensitive") {
		t.Fatal("SDK logs leaked raw arguments")
	}
	if !strings.Contains(output.String(), "ProviderError") {
		t.Fatal("safe error category missing")
	}
	for _, sandbox := range []bool{false, true} {
		if _, err := NewSender(secret.New("synthetic-app"), secret.New("synthetic-secret"), secret.New("synthetic-owner"), sandbox, logger); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := NewSender(secret.New(""), secret.New(""), secret.New(""), true, nil); err == nil {
		t.Fatal("missing SDK configuration accepted")
	}
}
