package qq

import (
	"log/slog"

	sdklog "github.com/tencent-connect/botgo/log"
)

// InstallSafeSDKLogger is called once in Bootstrap, before starting SDK goroutines.
// botgo token source logs credentials and raw responses at Debug level.
func InstallSafeSDKLogger(logger *slog.Logger) { sdklog.DefaultLogger = safeLogger{logger} }

type safeLogger struct{ log *slog.Logger }

func (safeLogger) Debug(...interface{})          {}
func (safeLogger) Debugf(string, ...interface{}) {}
func (safeLogger) Info(...interface{})           {}
func (safeLogger) Infof(string, ...interface{})  {}
func (s safeLogger) Warn(...interface{}) {
	s.log.Warn("QQ SDK warning", "failure_class", "ProviderWarning")
}
func (s safeLogger) Warnf(string, ...interface{}) { s.Warn() }
func (s safeLogger) Error(...interface{}) {
	s.log.Error("QQ SDK error", "failure_class", "ProviderError")
}
func (s safeLogger) Errorf(string, ...interface{}) { s.Error() }
func (safeLogger) Sync() error                     { return nil }
