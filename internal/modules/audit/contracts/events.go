package contracts

import (
	"context"
	"time"
)

// ConnectionEvent excludes account identities, credentials and provider payloads.
type ConnectionEvent struct {
	ID           string
	Kind         string
	ConnectionID string
	Actor        string
	Provider     string
	Status       string
	Version      int
	OccurredAt   time.Time
}

type ConnectionAudit interface {
	AppendConnection(context.Context, ConnectionEvent) error
}
