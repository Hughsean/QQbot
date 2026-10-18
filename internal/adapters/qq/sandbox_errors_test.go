package qq

import (
	"errors"
	"net"
	"strings"
	"testing"

	"github.com/tencent-connect/botgo/errs"
)

func TestSandboxErrorsExposeOnlyPhaseClassAndNumericCode(t *testing.T) {
	for _, err := range []error{
		errors.New("40013.synthetic-sensitive-value"),
		&net.DNSError{Err: "synthetic-sensitive-value"},
		errs.New(401, "synthetic-sensitive-value"), errs.New(403, "synthetic-sensitive-value"),
		errs.New(429, "synthetic-sensitive-value"), errs.New(503, "synthetic-sensitive-value"),
	} {
		result := probeError("gateway", err).Error()
		if strings.Contains(result, "synthetic-sensitive-value") || !strings.Contains(result, "gateway") {
			t.Fatal("probe leaked provider error")
		}
	}
}
