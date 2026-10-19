package application

import (
	"context"
	"errors"
	"strings"

	"golang.org/x/text/cases"
	"qqtimeagent/internal/modules/identity/contracts"
	"qqtimeagent/internal/modules/identity/domain"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/ids"
)

type Service struct {
	repository Repository
	defaults   contracts.Preferences
	clock      clock.Clock
}

func New(repository Repository, defaults contracts.Preferences, timeSource clock.Clock) (*Service, error) {
	if repository == nil || timeSource == nil {
		return nil, contracts.ErrInvalid
	}
	if err := domain.Validate(defaults); err != nil {
		return nil, err
	}
	defaults.WorkingWeekdays = append([]int32(nil), defaults.WorkingWeekdays...)
	return &Service{repository: repository, defaults: defaults, clock: timeSource}, nil
}

func (s *Service) Preferences(ctx context.Context, user string) (contracts.Preferences, error) {
	if user != "owner" {
		return contracts.Preferences{}, contracts.ErrSecurity
	}
	p, err := s.repository.Preferences(ctx, user)
	if errors.Is(err, contracts.ErrNotFound) {
		p, err = s.repository.Initialize(ctx, s.defaults)
	}
	if err != nil {
		return contracts.Preferences{}, err
	}
	if err := domain.Validate(p); err != nil {
		return contracts.Preferences{}, err
	}
	return p, nil
}

func (s *Service) Aliases(ctx context.Context, user string) ([]contracts.Alias, error) {
	if user != "owner" {
		return nil, contracts.ErrSecurity
	}
	return s.repository.Aliases(ctx, user)
}

func (s *Service) RegisterAlias(ctx context.Context, user, value string) (contracts.Alias, error) {
	if user != "owner" {
		return contracts.Alias{}, contracts.ErrSecurity
	}
	value = strings.Join(strings.Fields(value), " ")
	if value == "" || len([]rune(value)) > 64 {
		return contracts.Alias{}, contracts.ErrInvalid
	}
	return s.repository.AddAlias(ctx, user, contracts.Alias{Value: value}, cases.Fold().String(value), s.clock.Now())
}

func (s *Service) MailRules(ctx context.Context, user string) ([]contracts.MailRule, error) {
	if user != "owner" {
		return nil, contracts.ErrSecurity
	}
	return s.repository.MailRules(ctx, user)
}

func (s *Service) RegisterMailRule(ctx context.Context, user string, field contracts.MatchField, pattern string, action contracts.RuleAction) (contracts.MailRule, error) {
	if user != "owner" {
		return contracts.MailRule{}, contracts.ErrSecurity
	}
	pattern = strings.Join(strings.Fields(pattern), " ")
	if pattern == "" || len([]rune(pattern)) > 240 {
		return contracts.MailRule{}, contracts.ErrInvalid
	}
	if !validRule(field, action) {
		return contracts.MailRule{}, contracts.ErrInvalid
	}
	value := contracts.MailRule{ID: ids.New(), Field: field, Pattern: pattern, Action: action}
	return s.repository.PutMailRule(ctx, user, value, cases.Fold().String(pattern), s.clock.Now())
}

func validRule(field contracts.MatchField, action contracts.RuleAction) bool {
	return (field == contracts.Sender || field == contracts.Subject) && (action == contracts.Notify || action == contracts.Hold)
}
