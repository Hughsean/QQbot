package qq

import (
	"context"
	"strings"

	"qqtimeagent/internal/modules/inbox/contracts"
)

type probeObservation struct {
	externalID string
	matched    bool
}

// probeIntake observes only a fixed probe phrase; it is never a business Intake.
type probeIntake struct{ observations chan<- probeObservation }

func (p probeIntake) Receive(_ context.Context, envelope contracts.Envelope, content string, _ []contracts.Asset) error {
	if envelope.TrustLevel != "T1" || strings.TrimSpace(content) != "go-migration-probe" {
		return nil
	}
	select {
	case p.observations <- probeObservation{externalID: envelope.ExternalID, matched: true}:
	default:
	}
	return nil
}
