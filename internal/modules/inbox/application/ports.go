package application

import (
	"context"

	"qqtimeagent/internal/modules/inbox/contracts"
	"qqtimeagent/internal/modules/inbox/domain"
)

type Repository interface {
	Ingest(context.Context, domain.Envelope, contracts.RawContent) (contracts.IngestResult, error)
	Get(context.Context, string) (domain.Item, error)
	Save(context.Context, domain.Item, int) error
}
