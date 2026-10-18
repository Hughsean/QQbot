package qq

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"time"

	"github.com/tencent-connect/botgo"
	"github.com/tencent-connect/botgo/dto"
	"github.com/tencent-connect/botgo/openapi/options"
	"github.com/tencent-connect/botgo/token"

	"qqtimeagent/internal/modules/notifications/contracts"
	"qqtimeagent/internal/platform/secret"
)

var ErrAmbiguousDelivery = errors.New("QQ delivery outcome is unknown; do not automatically resend")

type messageAPI interface {
	PostC2CMessage(context.Context, string, dto.APIMessage, ...options.Option) (*dto.Message, error)
}

type Sender struct {
	API   messageAPI
	Owner secret.Value
}

// NewSender configures the official SDK without performing network calls.
// Bootstrap must call this before starting any QQ goroutine (SDK logger is global).
func NewSender(appID, appSecret, owner secret.Value, sandbox bool, logger *slog.Logger) (Sender, error) {
	if !appID.Present() || !appSecret.Present() || !owner.Present() || logger == nil {
		return Sender{}, errors.New("QQ credentials, owner and logger are required")
	}
	InstallSafeSDKLogger(logger)
	InstallSDKProtocolFilter()
	source := token.NewQQBotTokenSource(&token.QQBotCredentials{
		AppID: appID.Reveal(), AppSecret: appSecret.Reveal(),
	})
	api := botgo.NewOpenAPI(appID.Reveal(), source)
	if sandbox {
		api = botgo.NewSandboxOpenAPI(appID.Reveal(), source)
	}
	return Sender{API: api.WithTimeout(10 * time.Second).SetDebug(false), Owner: owner}, nil
}

// Send is exposed only to Notifications; the destination is always the owner.
// Active sends have no business idempotency key. Ambiguous outcomes are not retried.
func (s Sender) Send(ctx context.Context, message contracts.Message) (string, error) {
	if err := s.validate(message); err != nil {
		return "", err
	}
	if ctx.Err() != nil {
		return "", errors.New("QQ request cancelled before sending")
	}
	return s.sendOnce(ctx, message)
}

func (s Sender) validate(message contracts.Message) error {
	if s.API == nil || !s.Owner.Present() || strings.TrimSpace(message.Content) == "" || len(message.Content) > 16000 {
		return errors.New("invalid QQ message or sender")
	}
	if message.ReplyTo != "" && message.Sequence == 0 {
		return errors.New("reply sequence is required")
	}
	return nil
}

func (s Sender) sendOnce(ctx context.Context, message contracts.Message) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	result, err := s.API.PostC2CMessage(ctx, s.Owner.Reveal(), dto.MessageToCreate{
		Content: message.Content, MsgType: dto.TextMsg, MsgID: message.ReplyTo, MsgSeq: message.Sequence,
	})
	if err != nil || result == nil || result.ID == "" {
		return "", ErrAmbiguousDelivery
	}
	return result.ID, nil
}

var _ contracts.Sender = Sender{}
