// Package secret prevents accidental formatting and serialization of credentials.
package secret

import "log/slog"

type Value struct{ value string }

func New(value string) Value               { return Value{value: value} }
func (v Value) Reveal() string             { return v.value }
func (v Value) Present() bool              { return v.value != "" }
func (Value) String() string               { return "[REDACTED]" }
func (Value) GoString() string             { return "[REDACTED]" }
func (Value) MarshalText() ([]byte, error) { return []byte("[REDACTED]"), nil }
func (Value) MarshalJSON() ([]byte, error) { return []byte(`"[REDACTED]"`), nil }
func (Value) LogValue() slog.Value         { return slog.StringValue("[REDACTED]") }
