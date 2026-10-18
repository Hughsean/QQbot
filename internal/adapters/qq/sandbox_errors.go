package qq

import (
	"errors"
	"fmt"
	"net"
	"regexp"
	"strconv"
)

var tokenErrorCode = regexp.MustCompile(`^([0-9]{1,9})\.`)

func probeError(phase string, err error) error {
	class, code := "PermanentProvider", 0
	var coded interface{ Code() int }
	if errors.As(err, &coded) {
		code = coded.Code()
	} else if match := tokenErrorCode.FindStringSubmatch(err.Error()); len(match) == 2 {
		code, _ = strconv.Atoi(match[1])
	}
	var network net.Error
	if errors.As(err, &network) {
		class = "TransientProvider"
	}
	switch code {
	case 401, 40013, 40014:
		class = "Authentication"
	case 403:
		class = "Authorization"
	case 429:
		class = "RateLimit"
	case 500, 502, 503, 504:
		class = "TransientProvider"
	}
	return fmt.Errorf("QQ sandbox %s failed (%s, provider_code=%d)", phase, class, code)
}
