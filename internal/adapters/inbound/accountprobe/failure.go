package accountprobe

import (
	"errors"
	"fmt"

	"qqtimeagent/internal/modules/connections/contracts"
)

// Stage names are constants supplied by the probe, never callback parameters.
// Unknown errors are replaced because an implementation may embed secrets.
func stageFailure(stage string, err error) error {
	var provider contracts.ProviderError
	if errors.As(err, &provider) {
		switch provider.Class {
		case "Authentication", "Permission", "RateLimit", "TransientProvider", "PermanentProvider", "InvalidResponse":
			return fmt.Errorf("microsoft sandbox %s: %w", stage, provider)
		}
	}
	return fmt.Errorf("microsoft sandbox %s failed", stage)
}
