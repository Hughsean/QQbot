// Package contracts defines Provider-neutral source ingress.
package contracts

import (
	"context"
	"time"
)

type Envelope struct {
	SourceType       string
	IngressType      string
	ExternalID       string
	OccurredAt       time.Time
	ReceivedAt       time.Time
	SenderID         string
	ContentRef       string
	ContentHash      string
	TrustLevel       string
	ProviderSequence *int64
	ReferenceHash    string
}

type Asset struct {
	ProviderID   string
	Locator      string
	Filename     string
	ContentType  string
	DeclaredSize int
}

type Intake interface {
	Receive(context.Context, Envelope, string, []Asset) error
}
