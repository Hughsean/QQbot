// Package jobs defines the operational queue; modules never share repositories.
package jobs

import (
	"context"
	"encoding/json"
	"errors"
	"time"
)

var ErrStaleLease = errors.New("job lease is stale or no longer owned")

type Request struct {
	ID             string
	Kind           string
	Payload        json.RawMessage
	IdempotencyKey string
	AvailableAt    time.Time
	MaxAttempts    int
}

type Lease struct {
	ID          string
	Kind        string
	Payload     json.RawMessage
	Owner       string
	Attempt     int
	MaxAttempts int
}

type Queue interface {
	Enqueue(context.Context, Request) (string, error)
	LeaseDue(context.Context, time.Time, string, []string, int, time.Duration) ([]Lease, error)
	Complete(context.Context, Lease, time.Time) error
	Fail(context.Context, Lease, time.Time, string, *time.Time) error
}
