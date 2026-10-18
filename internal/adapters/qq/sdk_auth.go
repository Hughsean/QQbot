package qq

import (
	"errors"
	"net/http"
	"strings"
	"sync"

	"github.com/tencent-connect/botgo/openapi"
)

var sdkProtocolFilter sync.Once

// InstallSDKProtocolFilter uses botgo's public filter extension at initialization.
// The filter captures no credential or service; it normalizes only the auth scheme.
func InstallSDKProtocolFilter() {
	sdkProtocolFilter.Do(func() { openapi.RegisterReqFilter("qq-time-agent-auth-scheme-v1", qqBotAuthScheme) })
}

func qqBotAuthScheme(req *http.Request, _ *http.Response) error {
	if req.Header.Get("X-Union-Appid") == "" {
		return errors.New("QQ SDK application identity missing")
	}
	header := req.Header.Get("Authorization")
	if strings.HasPrefix(header, "Bearer ") {
		req.Header.Set("Authorization", "QQBot "+strings.TrimPrefix(header, "Bearer "))
		return nil
	}
	if !strings.HasPrefix(header, "QQBot ") {
		return errors.New("QQ SDK authentication scheme invalid")
	}
	return nil
}
