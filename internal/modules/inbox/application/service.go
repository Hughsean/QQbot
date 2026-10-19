package application

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"strings"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/modules/inbox/domain"
	"qqtimeagent/internal/platform/clock"
	"qqtimeagent/internal/platform/ids"
)

type Service struct {
	repository Repository
	clock      clock.Clock
}

func New(repository Repository, timeSource clock.Clock) (*Service, error) {
	if repository == nil || timeSource == nil {
		return nil, contracts.ErrInvalid
	}
	return &Service{repository: repository, clock: timeSource}, nil
}

func (s *Service) IngestMail(ctx context.Context, connectionID, userID, sourceType string, change contracts.MailChange) (contracts.IngestResult, error) {
	if userID != "owner" || (sourceType != "MICROSOFT_MAIL" && sourceType != "QQ_MAIL") {
		return contracts.IngestResult{}, contracts.ErrInvalid
	}
	raw, err := rawMail(change)
	if err != nil {
		return contracts.IngestResult{}, err
	}
	hash := sha256.Sum256([]byte(change.Subject + "\x00" + change.Body))
	e := domain.Envelope{ConnectionID: connectionID, UserID: userID, ExternalID: change.ExternalID, DedupeKey: change.DedupeKey, ThreadID: change.ThreadID, SenderID: change.Sender.Address, SenderDisplay: change.Sender.DisplayName, ContentHash: hex.EncodeToString(hash[:]), SourceType: sourceType, IngressType: "SYNC", TrustLevel: "T2", OccurredAt: change.OccurredAt, ReceivedAt: s.clock.Now()}
	if e.Validate() != nil {
		return contracts.IngestResult{}, contracts.ErrInvalid
	}
	return s.repository.Ingest(ctx, e, raw)
}

var _ contracts.Processing = (*Service)(nil)

func rawMail(change contracts.MailChange) (contracts.RawContent, error) {
	if err := validateMail(change); err != nil {
		return contracts.RawContent{}, err
	}
	raw := contracts.RawContent{Subject: change.Subject, MIMEType: change.ContentType, Recipients: change.Recipients, InternetMessageID: change.InternetMessageID, ChangeKey: change.ChangeKey, HasAttachments: change.HasAttachments, Attachments: change.Attachments}
	switch strings.ToLower(change.ContentType) {
	case "text", "text/plain":
		raw.BodyText = change.Body
	case "html", "text/html":
		raw.BodyHTML = change.Body
	default:
		return contracts.RawContent{}, contracts.ErrInvalid
	}
	return raw, nil
}

func (s *Service) transition(ctx context.Context, id string, target domain.Status) error {
	if ids.Validate(id) != nil {
		return contracts.ErrInvalid
	}
	item, err := s.repository.Get(ctx, id)
	if err != nil {
		return err
	}
	if item.Status == target && target != domain.Normalized && target != domain.Received {
		return nil
	}
	version := item.Version
	if err := item.Transition(target); err != nil {
		return err
	}
	return s.repository.Save(ctx, item, version)
}

func (s *Service) MarkNormalized(ctx context.Context, id string) error {
	return s.transition(ctx, id, domain.Normalized)
}
func (s *Service) MarkUnderstood(ctx context.Context, id string) error {
	return s.transition(ctx, id, domain.Understood)
}
func (s *Service) MarkProposed(ctx context.Context, id string) error {
	return s.transition(ctx, id, domain.Proposed)
}
func (s *Service) MarkCompleted(ctx context.Context, id string) error {
	return s.transition(ctx, id, domain.Completed)
}
func (s *Service) MarkIgnored(ctx context.Context, id string) error {
	return s.transition(ctx, id, domain.Ignored)
}
func (s *Service) MarkNeedsReview(ctx context.Context, id string) error {
	return s.transition(ctx, id, domain.NeedsReview)
}
func (s *Service) Retry(ctx context.Context, id string) error {
	return s.transition(ctx, id, domain.Received)
}

func (s *Service) Fail(ctx context.Context, id, class string, retryable bool) error {
	if ids.Validate(id) != nil {
		return contracts.ErrInvalid
	}
	item, err := s.repository.Get(ctx, id)
	if err != nil {
		return err
	}
	version := item.Version
	if err := item.Fail(class, retryable); err != nil {
		return err
	}
	return s.repository.Save(ctx, item, version)
}
