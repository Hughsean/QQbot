package qq

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"time"

	"github.com/tencent-connect/botgo"
	"github.com/tencent-connect/botgo/dto"
	"github.com/tencent-connect/botgo/event"
	"github.com/tencent-connect/botgo/token"
	"github.com/tencent-connect/botgo/websocket"

	notifications "qqtimeagent/internal/modules/notifications/contracts"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/secret"
)

type SandboxConfig struct {
	AppID     secret.Value
	AppSecret secret.Value
	Owner     secret.Value
	Sandbox   bool
	AllowSend bool
}

// Sandbox performs two fresh outgoing connections, an active send and owner reply.
// It runs as a dedicated bounded process and never accesses application databases.
func Sandbox(ctx context.Context, config SandboxConfig, logger *slog.Logger) error {
	if logger == nil {
		return errors.New("QQ sandbox logger is required")
	}
	if err := validateSandbox(config); err != nil {
		return err
	}
	InstallSafeSDKLogger(logger)
	InstallSDKProtocolFilter()
	source := token.NewQQBotTokenSource(&token.QQBotCredentials{AppID: config.AppID.Reveal(), AppSecret: config.AppSecret.Reveal()})
	if _, err := source.Token(); err != nil {
		return probeError("authentication", err)
	}
	logger.Info("QQ sandbox authentication verified")
	api := botgo.NewSandboxOpenAPI(config.AppID.Reveal(), source).WithTimeout(10 * time.Second).SetDebug(false)
	info, err := api.WS(ctx, nil, "")
	if err != nil {
		return probeError("gateway", err)
	}
	if err := validateGateway(info); err != nil {
		return err
	}
	ready := make(chan struct{}, 4)
	observations := make(chan probeObservation, 4)
	sink := probeIntake{observations: observations}
	ingress := Ingress{Owner: config.Owner, Clock: clock.System{}, Intake: sink}
	intents := event.RegisterHandlers(event.ReadyHandler(func(*dto.WSPayload, *dto.WSReadyData) {
		select {
		case ready <- struct{}{}:
		default:
		}
	}), ingress.Handler(ctx))
	sender := Sender{API: api, Owner: config.Owner}
	session := dto.Session{URL: info.URL, TokenSource: source, Intent: intents, Shards: dto.ShardConfig{ShardID: 0, ShardCount: info.Shards}}
	if err := runProbeSessions(ctx, sender, session, ready, observations, websocket.ClientImpl.New, sessionPause); err != nil {
		return err
	}
	logger.Info("QQ sandbox passed", "outbound_websocket", true, "owner_receive", true, "active_and_reply_send", true, "fresh_reconnect", true)
	return nil
}

func runProbeSessions(ctx context.Context, sender Sender, session dto.Session, ready <-chan struct{}, observations <-chan probeObservation, factory func(dto.Session) websocket.WebSocket, pause func(context.Context) error) error {
	for connection := range 2 {
		client := factory(session)
		if err := probeConnection(ctx, client, ready, func() error { return exchangeProbe(ctx, sender, observations, connection) }); err != nil {
			return err
		}
		if connection == 0 {
			if err := pause(ctx); err != nil {
				return err
			}
		}
	}
	return nil
}

func sessionPause(ctx context.Context) error {
	timer := time.NewTimer(5 * time.Second)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return errors.New("QQ sandbox cancelled")
	case <-timer.C:
		return nil
	}
}

func validateSandbox(c SandboxConfig) error {
	if !c.Sandbox || !c.AllowSend {
		return errors.New("QQ sandbox requires sandbox mode and explicit --allow-send")
	}
	if !c.AppID.Present() || !c.AppSecret.Present() || !c.Owner.Present() {
		return errors.New("QQ sandbox credentials and owner are required")
	}
	return nil
}

func validateGateway(info *dto.WebsocketAP) error {
	if info == nil || info.Shards == 0 {
		return errors.New("invalid QQ gateway metadata")
	}
	u, err := url.Parse(info.URL)
	if err != nil || u.Scheme != "wss" || u.Hostname() == "" || u.User != nil {
		return errors.New("QQ gateway must use WSS")
	}
	if info.SessionStartLimit.Remaining < 2 || info.SessionStartLimit.MaxConcurrency == 0 {
		return errors.New("QQ sandbox requires two available session starts")
	}
	return nil
}

func probeConnection(ctx context.Context, client websocket.WebSocket, ready <-chan struct{}, exchange func() error) error {
	if err := client.Connect(); err != nil {
		return errors.New("QQ sandbox websocket connect failed")
	}
	defer client.Close()
	if err := client.Identify(); err != nil {
		return errors.New("QQ sandbox identify failed")
	}
	done := make(chan error, 1)
	go func() { done <- client.Listening() }()
	select {
	case <-ctx.Done():
		return errors.New("QQ sandbox ready timed out")
	case <-done:
		return errors.New("QQ sandbox disconnected before ready")
	case <-ready:
		return exchange()
	}
}

func exchangeProbe(ctx context.Context, sender Sender, observations <-chan probeObservation, connection int) error {
	if connection == 1 {
		_, err := sender.Send(ctx, notifications.Message{Content: "Go SDK 迁移沙箱：出站 WebSocket 重新连接成功。"})
		return err
	}
	if _, err := sender.Send(ctx, notifications.Message{Content: "Go SDK 迁移沙箱：已连接，请回复 go-migration-probe。此测试不修改日程。"}); err != nil {
		return err
	}
	for {
		select {
		case <-ctx.Done():
			return errors.New("QQ sandbox waiting for owner reply timed out")
		case observed := <-observations:
			if !observed.matched {
				continue
			}
			_, err := sender.Send(ctx, notifications.Message{Content: "Go SDK 迁移沙箱：所有者消息接收和被动回复成功。", ReplyTo: observed.externalID, Sequence: 1})
			return err
		}
	}
}
