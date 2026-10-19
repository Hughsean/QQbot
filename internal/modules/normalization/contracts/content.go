// Package contracts exposes deterministic source normalization, never commands.
package contracts

import (
	"context"
	"errors"
	"log/slog"
)

var (
	ErrInvalid       = errors.New("invalid normalization input")
	ErrResourceLimit = errors.New("normalization resource limit exceeded")
	ErrStorage       = errors.New("normalization persistence failed")
)

type Input struct {
	InboxItemID, Subject, BodyText, BodyHTML, SourceHash, SourceRef string
}

type Content struct {
	InboxItemID       string
	Subject           string
	Body              string
	SourceHash        string
	NormalizerVersion string
	SourceRef         string
}

type Normalizer interface {
	Normalize(context.Context, Input) (Content, error)
}
type Query interface {
	Get(context.Context, string) (Content, error)
}

// General purpose logs redact untrusted source text and metadata.
func (Input) String() string         { return "NormalizationInput([REDACTED])" }
func (Input) GoString() string       { return "NormalizationInput([REDACTED])" }
func (Content) String() string       { return "NormalizedContent([REDACTED])" }
func (Content) GoString() string     { return "NormalizedContent([REDACTED])" }
func (Input) LogValue() slog.Value   { return slog.StringValue("NormalizationInput([REDACTED])") }
func (Content) LogValue() slog.Value { return slog.StringValue("NormalizedContent([REDACTED])") }
