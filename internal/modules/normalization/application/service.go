package application

import (
	"context"
	"encoding/hex"
	"strings"
	"unicode/utf8"

	"qqtimeagent/internal/modules/normalization/contracts"
	"qqtimeagent/internal/modules/normalization/domain"
	"qqtimeagent/internal/platform/ids"
)

const MaxInputBytes = 8 << 20

type Repository interface {
	Upsert(context.Context, contracts.Content) error
	Get(context.Context, string) (contracts.Content, error)
}
type HTMLText interface {
	Extract(context.Context, string) (string, error)
}

type Service struct {
	repository Repository
	html       HTMLText
}

func New(repository Repository, html HTMLText) (*Service, error) {
	if repository == nil || html == nil {
		return nil, contracts.ErrInvalid
	}
	return &Service{repository: repository, html: html}, nil
}

func (s *Service) Normalize(ctx context.Context, input contracts.Input) (contracts.Content, error) {
	if err := validate(input); err != nil {
		return contracts.Content{}, err
	}
	if err := ctx.Err(); err != nil {
		return contracts.Content{}, err
	}
	body := input.BodyText
	if strings.TrimSpace(body) == "" {
		var err error
		body, err = s.html.Extract(ctx, input.BodyHTML)
		if err != nil {
			return contracts.Content{}, err
		}
	}
	subject, body := domain.Normalize(input.Subject, body)
	value := contracts.Content{InboxItemID: input.InboxItemID, Subject: subject, Body: body, SourceHash: input.SourceHash, NormalizerVersion: domain.Version, SourceRef: input.SourceRef}
	if err := ctx.Err(); err != nil {
		return contracts.Content{}, err
	}
	if err := s.repository.Upsert(ctx, value); err != nil {
		return contracts.Content{}, err
	}
	return value, nil
}

func (s *Service) Get(ctx context.Context, id string) (contracts.Content, error) {
	if ids.Validate(id) != nil {
		return contracts.Content{}, contracts.ErrInvalid
	}
	return s.repository.Get(ctx, id)
}

func validate(input contracts.Input) error {
	if len(input.Subject)+len(input.BodyText)+len(input.BodyHTML) > MaxInputBytes {
		return contracts.ErrResourceLimit
	}
	if ids.Validate(input.InboxItemID) != nil || len(input.SourceRef) > 512 {
		return contracts.ErrInvalid
	}
	hash, err := hex.DecodeString(input.SourceHash)
	if err != nil || len(hash) != 32 {
		return contracts.ErrInvalid
	}
	for _, value := range []string{input.Subject, input.BodyText, input.BodyHTML, input.SourceRef} {
		if !utf8.ValidString(value) || strings.ContainsRune(value, 0) {
			return contracts.ErrInvalid
		}
	}
	return nil
}
