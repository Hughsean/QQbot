package qq

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"

	"github.com/tencent-connect/botgo/dto"
	"github.com/tencent-connect/botgo/websocket"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/platform/secret"
)

type fakeSocket struct {
	ready                              chan<- struct{}
	stop                               chan struct{}
	once                               sync.Once
	connectErr, identifyErr, listenErr error
}

func (s *fakeSocket) New(dto.Session) websocket.WebSocket { return s }
func (s *fakeSocket) Connect() error                      { return s.connectErr }
func (s *fakeSocket) Identify() error                     { return s.identifyErr }
func (s *fakeSocket) Session() *dto.Session               { return &dto.Session{} }
func (s *fakeSocket) Resume() error                       { return nil }
func (s *fakeSocket) Write(*dto.WSPayload) error          { return nil }
func (s *fakeSocket) Close()                              { s.once.Do(func() { close(s.stop) }) }
func (s *fakeSocket) Listening() error {
	if s.listenErr != nil {
		return s.listenErr
	}
	if s.ready != nil {
		s.ready <- struct{}{}
	}
	<-s.stop
	return nil
}

func TestSandboxRequiresExplicitSendAndValidConfiguration(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	for _, config := range []SandboxConfig{{}, {Sandbox: true, AllowSend: true}} {
		if Sandbox(context.Background(), config, logger) == nil {
			t.Fatal("unapproved or unconfigured sandbox accepted")
		}
	}
	if Sandbox(context.Background(), SandboxConfig{}, nil) == nil {
		t.Fatal("missing logger accepted")
	}
	valid := SandboxConfig{Sandbox: true, AllowSend: true, AppID: secret.New("synthetic-app"), AppSecret: secret.New("synthetic-secret"), Owner: secret.New("synthetic-owner")}
	if err := validateSandbox(valid); err != nil {
		t.Fatal(err)
	}
	for _, info := range []*dto.WebsocketAP{nil, {}, {Shards: 1, URL: "http://synthetic.example"}, {Shards: 1, URL: "wss://synthetic.example"}} {
		if validateGateway(info) == nil {
			t.Fatal("invalid gateway accepted")
		}
	}
	if err := validateGateway(&dto.WebsocketAP{Shards: 1, URL: "wss://synthetic.example", SessionStartLimit: dto.SessionStartLimit{Remaining: 2, MaxConcurrency: 1}}); err != nil {
		t.Fatal(err)
	}
}

func TestSandboxSessionsExerciseActiveReplyAndReconnect(t *testing.T) {
	ready := make(chan struct{}, 2)
	observed := make(chan probeObservation, 2)
	observed <- probeObservation{matched: false}
	observed <- probeObservation{matched: true, externalID: "synthetic-inbound"}
	api := &fakeAPI{result: &dto.Message{ID: "synthetic-delivery"}}
	sender := Sender{API: api, Owner: secret.New("synthetic-owner")}
	connections := 0
	factory := func(dto.Session) websocket.WebSocket {
		connections++
		return &fakeSocket{ready: ready, stop: make(chan struct{})}
	}
	err := runProbeSessions(context.Background(), sender, dto.Session{}, ready, observed, factory, func(context.Context) error { return nil })
	if err != nil || connections != 2 || api.called != 3 {
		t.Fatalf("probe did not verify full sequence: %v", err)
	}
}

func TestSandboxRejectsConnectionAndExchangeFailures(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	for _, socket := range []*fakeSocket{
		{stop: make(chan struct{}), connectErr: errors.New("synthetic-sensitive")},
		{stop: make(chan struct{}), identifyErr: errors.New("synthetic-sensitive")},
		{stop: make(chan struct{})},
		{stop: make(chan struct{}), listenErr: errors.New("synthetic-sensitive")},
	} {
		if probeConnection(ctx, socket, make(chan struct{}), func() error { return nil }) == nil {
			t.Fatal("connection failure accepted")
		}
	}
	api := &fakeAPI{err: errors.New("synthetic-failure")}
	sender := Sender{API: api, Owner: secret.New("synthetic-owner")}
	if exchangeProbe(ctx, sender, make(chan probeObservation), 0) == nil {
		t.Fatal("cancelled exchange accepted")
	}
	if exchangeProbe(context.Background(), sender, make(chan probeObservation), 0) == nil {
		t.Fatal("send failure accepted")
	}
	if sessionPause(ctx) == nil {
		t.Fatal("cancelled reconnect pause accepted")
	}
}

func TestSandboxProbePhraseCannotBeTriggeredByForwardedContent(t *testing.T) {
	observed := make(chan probeObservation, 1)
	p := probeIntake{observations: observed}
	for _, trust := range []string{"T2", "T3"} {
		_ = p.Receive(context.Background(), contracts.Envelope{TrustLevel: trust}, "go-migration-probe", nil)
	}
	if len(observed) != 0 {
		t.Fatal("untrusted content triggered sandbox reply")
	}
	_ = p.Receive(context.Background(), contracts.Envelope{TrustLevel: "T1", ExternalID: "synthetic"}, "go-migration-probe", nil)
	if len(observed) != 1 {
		t.Fatal("owner phrase was not observed")
	}
	_ = p.Receive(context.Background(), contracts.Envelope{TrustLevel: "T1"}, "go-migration-probe", nil)
}
