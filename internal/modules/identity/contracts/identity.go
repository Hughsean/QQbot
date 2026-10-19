package contracts

import (
	"context"
	"errors"
	"time"

	"qqtimeagent/internal/platform/secret"
)

var (
	ErrInvalid   = errors.New("invalid owner identity data")
	ErrSecurity  = errors.New("owner authentication required")
	ErrForbidden = errors.New("signed identity is not authorized")
	ErrNotFound  = errors.New("owner identity data does not exist")
	ErrStorage   = errors.New("owner identity persistence failed")
)

// LocalTime is microseconds since local midnight, interpreted in Timezone.
// Weekdays use Python's Monday=0 convention, preserving existing preferences.
type LocalTime int64
type Preferences struct {
	UserID                                                   string
	Timezone                                                 string
	WorkStart, WorkEnd, LunchStart, LunchEnd                 LocalTime
	WorkingWeekdays                                          []int32
	DefaultEventMinutes, DefaultTaskMinutes                  int
	DigestEnabled                                            bool
	DigestLocalTime                                          LocalTime
	ConflictNotificationsEnabled, ReauthNotificationsEnabled bool
	QuietHoursEnabled                                        bool
	QuietStart, QuietEnd                                     LocalTime
}

type Alias struct{ Value string }
type MatchField string
type RuleAction string

const (
	Sender  MatchField = "SENDER"
	Subject MatchField = "SUBJECT"
	Notify  RuleAction = "NOTIFY"
	Hold    RuleAction = "HOLD"
)

type MailRule struct {
	ID      string
	Field   MatchField
	Pattern string
	Action  RuleAction
}
type PreferencesQuery interface {
	Preferences(context.Context, string) (Preferences, error)
}
type Aliases interface {
	Aliases(context.Context, string) ([]Alias, error)
	RegisterAlias(context.Context, string, string) (Alias, error)
}
type MailRules interface {
	MailRules(context.Context, string) ([]MailRule, error)
	RegisterMailRule(context.Context, string, MatchField, string, RuleAction) (MailRule, error)
}
type Session struct {
	UserID    string
	ExpiresAt time.Time
}
type SessionAuthority interface {
	Issue(string, time.Duration) (secret.Value, error)
	Verify(secret.Value) (Session, error)
}
