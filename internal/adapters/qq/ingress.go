// Package qq contains the official botgo SDK and all QQ-specific DTOs.
package qq

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/tencent-connect/botgo/dto"
	"github.com/tencent-connect/botgo/event"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/secret"
)

type Ingress struct {
	Owner  secret.Value
	Clock  clock.Clock
	Intake contracts.Intake
}

// Additional official fields are decoded locally: v0.2.1 omits user_openid/msg_seq.
type c2cPayload struct {
	Data struct {
		ID        string `json:"id"`
		Content   string `json:"content"`
		Timestamp string `json:"timestamp"`
		Author    struct {
			OpenID string `json:"user_openid"`
		} `json:"author"`
		Sequence    *int64                   `json:"msg_seq"`
		Reference   *dto.MessageReference    `json:"message_reference"`
		Attachments []*dto.MessageAttachment `json:"attachments"`
	} `json:"d"`
}

func (i Ingress) Handler(ctx context.Context) event.C2CMessageEventHandler {
	return func(payload *dto.WSPayload, _ *dto.WSC2CMessageData) error {
		if payload == nil {
			return errors.New("missing QQ event")
		}
		return i.Receive(ctx, payload.RawMessage)
	}
}

func (i Ingress) Receive(ctx context.Context, raw []byte) error {
	if len(raw) > 2*1024*1024 {
		return errors.New("QQ event exceeds limit")
	}
	var payload c2cPayload
	if json.Unmarshal(raw, &payload) != nil {
		return errors.New("invalid QQ event")
	}
	d := payload.Data
	if !i.Owner.Present() {
		return errors.New("QQ owner must be configured")
	}
	if subtle.ConstantTimeCompare([]byte(d.Author.OpenID), []byte(i.Owner.Reveal())) != 1 {
		return nil
	}
	if i.Intake == nil || i.Clock == nil {
		return errors.New("QQ intake is not configured")
	}
	envelope, text, err := i.envelope(payload)
	if err != nil {
		return err
	}
	assets, err := mapAssets(d.Attachments)
	if err != nil {
		return err
	}
	return i.Intake.Receive(ctx, envelope, text, assets)
}

func (i Ingress) envelope(payload c2cPayload) (contracts.Envelope, string, error) {
	d := payload.Data
	when, err := time.Parse(time.RFC3339Nano, d.Timestamp)
	if err != nil || d.ID == "" {
		return contracts.Envelope{}, "", errors.New("invalid QQ identity or timestamp")
	}
	source, ingress, trust, text, err := classifyText(d.Content)
	if err != nil {
		return contracts.Envelope{}, "", err
	}
	envelope := contracts.Envelope{SourceType: source, IngressType: ingress, TrustLevel: trust,
		ExternalID: d.ID, OccurredAt: when, ReceivedAt: i.Clock.Now(), SenderID: d.Author.OpenID,
		ContentRef: "qq:" + d.ID, ContentHash: "sha256:" + hash(text), ProviderSequence: d.Sequence}
	if d.Sequence != nil && *d.Sequence < 0 {
		envelope.ProviderSequence = nil
	}
	if d.Reference != nil && d.Reference.MessageID != "" {
		envelope.ReferenceHash = hash(d.Reference.MessageID)
	}
	return envelope, text, nil
}

func classifyText(content string) (string, string, string, string, error) {
	text := strings.TrimSpace(content)
	for _, prefix := range []string{"转发:", "转发：", "[聊天记录]", "[合并转发]", "【聊天记录】", "【合并转发】", "聊天记录:", "聊天记录："} {
		if strings.HasPrefix(text, prefix) {
			body := strings.TrimSpace(strings.TrimPrefix(text, prefix))
			if body == "" {
				return "", "", "", "", errors.New("empty forwarded text")
			}
			return "QQ_FORWARD", "FORWARDED", "T2", body, nil
		}
	}
	for _, prefix := range []string{"笔记:", "笔记："} {
		if strings.HasPrefix(text, prefix) {
			body := strings.TrimSpace(strings.TrimPrefix(text, prefix))
			if body == "" {
				return "", "", "", "", errors.New("empty owner note")
			}
			return "OWNER_NOTE", "DIRECT", "T2", body, nil
		}
	}
	return "QQ_DIRECT", "DIRECT", "T1", content, nil
}

func mapAssets(values []*dto.MessageAttachment) ([]contracts.Asset, error) {
	if len(values) > 32 {
		return nil, errors.New("too many QQ attachments")
	}
	assets := make([]contracts.Asset, 0, len(values))
	for _, a := range values {
		if a == nil || a.URL == "" || a.Size < 0 {
			return nil, errors.New("invalid QQ attachment")
		}
		mime := a.ContentType
		if mime == "" {
			mime = "image/unknown"
		}
		if !strings.HasPrefix(strings.ToLower(mime), "image/") {
			return nil, errors.New("unsupported QQ attachment type")
		}
		assets = append(assets, contracts.Asset{ProviderID: hash(a.URL), Locator: a.URL,
			Filename: a.FileName, ContentType: mime, DeclaredSize: a.Size})
	}
	return assets, nil
}

func hash(value string) string {
	h := sha256.Sum256([]byte(value))
	return hex.EncodeToString(h[:])
}
