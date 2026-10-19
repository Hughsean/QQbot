package application

import (
	"context"
	"time"

	"qqtimeagent/internal/modules/identity/contracts"
)

type Repository interface {
	Preferences(context.Context, string) (contracts.Preferences, error)
	Initialize(context.Context, contracts.Preferences) (contracts.Preferences, error)
	Aliases(context.Context, string) ([]contracts.Alias, error)
	AddAlias(context.Context, string, contracts.Alias, string, time.Time) (contracts.Alias, error)
	MailRules(context.Context, string) ([]contracts.MailRule, error)
	PutMailRule(context.Context, string, contracts.MailRule, string, time.Time) (contracts.MailRule, error)
}
