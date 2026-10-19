// Package domain owns Inbox processing state, independent of Providers and SQL.
package domain

import "errors"

var ErrTransition = errors.New("invalid Inbox state transition")

type Status string

const (
	Received        Status = "RECEIVED"
	Normalized      Status = "NORMALIZED"
	Understood      Status = "UNDERSTOOD"
	Proposed        Status = "PROPOSED"
	Completed       Status = "COMPLETED"
	Ignored         Status = "IGNORED"
	NeedsReview     Status = "NEEDS_REVIEW"
	FailedRetryable Status = "FAILED_RETRYABLE"
	FailedFinal     Status = "FAILED_FINAL"
)

type Item struct {
	ID, RawContentID    string
	Envelope            Envelope
	Status              Status
	FailureClass        string
	RetryCount, Version int
}

func Receive(id, rawID string, envelope Envelope) (Item, error) {
	if err := envelope.Validate(); err != nil {
		return Item{}, err
	}
	if !validID(id) || !validID(rawID) {
		return Item{}, ErrEnvelope
	}
	return Item{ID: id, RawContentID: rawID, Envelope: envelope, Status: Received, Version: 1}, nil
}

func (i *Item) Transition(target Status) error {
	if !allowed(i.Status, target) {
		return ErrTransition
	}
	i.Status, i.FailureClass = target, ""
	i.Version++
	return nil
}

func allowed(from, to Status) bool {
	switch to {
	case Received:
		return from == FailedRetryable
	case Normalized:
		return from == Received || from == FailedRetryable
	case Understood, NeedsReview, Ignored:
		return from == Normalized
	case Proposed:
		return from == Understood
	case Completed:
		return from == Normalized || from == Understood || from == Proposed
	default:
		return false
	}
}

func (i *Item) Fail(class string, retryable bool) error {
	if !validFailure(class) || i.terminal() {
		return ErrTransition
	}
	i.Status = FailedFinal
	if retryable {
		i.Status = FailedRetryable
	}
	i.FailureClass = class
	i.RetryCount++
	i.Version++
	return nil
}

func (i Item) terminal() bool {
	return i.Status == Completed || i.Status == Ignored || i.Status == FailedFinal
}

func validFailure(class string) bool {
	return validField(class, 80, true)
}
