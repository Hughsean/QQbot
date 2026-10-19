package microsoft

import "log/slog"

// These DTOs are encoded only for the encrypted flow store / decoded at the
// provider boundary. General-purpose formatting and structured logs redact them.
func (flowState) String() string           { return "OAuthFlow([REDACTED])" }
func (flowState) GoString() string         { return "OAuthFlow([REDACTED])" }
func (flowState) LogValue() slog.Value     { return slog.StringValue("OAuthFlow([REDACTED])") }
func (tokenResponse) String() string       { return "OAuthTokens([REDACTED])" }
func (tokenResponse) GoString() string     { return "OAuthTokens([REDACTED])" }
func (tokenResponse) LogValue() slog.Value { return slog.StringValue("OAuthTokens([REDACTED])") }
