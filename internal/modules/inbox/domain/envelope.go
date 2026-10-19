package domain

import (
	"encoding/hex"
	"errors"
	"strings"
	"time"
	"unicode/utf8"

	"qqtimeagent/internal/platform/ids"
)

var ErrEnvelope = errors.New("invalid Inbox envelope")

type Envelope struct {
	ConnectionID, UserID, ExternalID, DedupeKey, ThreadID string
	SenderID, SenderDisplay, ContentHash                  string
	SourceType, IngressType, TrustLevel                   string
	OccurredAt, ReceivedAt                                time.Time
}

func (e Envelope) Validate() error {
	if !validID(e.ConnectionID) || e.OccurredAt.IsZero() || e.ReceivedAt.IsZero() {
		return ErrEnvelope
	}
	for _, field := range []struct {
		value    string
		limit    int
		required bool
	}{
		{e.UserID, 120, true}, {e.ExternalID, 512, true}, {e.SenderID, 320, true},
		{e.DedupeKey, 512, false}, {e.ThreadID, 512, false}, {e.SenderDisplay, 320, false},
	} {
		if !validField(field.value, field.limit, field.required) {
			return ErrEnvelope
		}
	}
	decoded, err := hex.DecodeString(e.ContentHash)
	if err != nil || len(decoded) != 32 || !validTrust(e) {
		return ErrEnvelope
	}
	return nil
}

func validID(value string) bool { return ids.Validate(value) == nil }

func validField(value string, limit int, required bool) bool {
	return utf8.ValidString(value) && !strings.ContainsRune(value, 0) && utf8.RuneCountInString(value) <= limit && (!required || strings.TrimSpace(value) != "")
}

func validTrust(e Envelope) bool {
	switch e.SourceType {
	case "MICROSOFT_MAIL", "QQ_MAIL":
		return e.IngressType == "SYNC" && e.TrustLevel == "T2"
	case "QQ_DIRECT":
		return e.IngressType == "DIRECT" && e.TrustLevel == "T1"
	case "QQ_FORWARD":
		return e.IngressType == "FORWARDED" && e.TrustLevel == "T2"
	case "OWNER_NOTE":
		return e.IngressType == "DIRECT" && e.TrustLevel == "T2"
	default:
		return false
	}
}
