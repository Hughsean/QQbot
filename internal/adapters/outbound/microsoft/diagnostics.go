package microsoft

import "encoding/json"

// Only fixed protocol codes may leave the adapter. Provider descriptions and
// unknown codes can contain account data, URLs or tokens and are never logged.
func safeProviderCode(data []byte) string {
	var payload struct {
		Error json.RawMessage `json:"error"`
	}
	if json.Unmarshal(data, &payload) != nil {
		return "unknown"
	}
	var code string
	if json.Unmarshal(payload.Error, &code) != nil {
		var graphError struct {
			Code string `json:"code"`
		}
		if json.Unmarshal(payload.Error, &graphError) != nil {
			return "unknown"
		}
		code = graphError.Code
	}
	switch code {
	case "invalid_request", "invalid_client", "invalid_grant", "invalid_scope",
		"unauthorized_client", "unsupported_grant_type", "access_denied",
		"interaction_required", "login_required", "consent_required",
		"temporarily_unavailable", "server_error", "invalid_resource",
		"BadRequest", "Request_BadRequest", "InvalidAuthenticationToken",
		"ErrorAccessDenied", "Authorization_RequestDenied", "ErrorInvalidUser":
		return code
	default:
		return "unknown"
	}
}
