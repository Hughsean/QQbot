// Package httpaccounts maps the existing loopback-only account HTTP contracts.
package httpaccounts

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"

	"qqtimeagent/internal/modules/connections/contracts"
	identity "qqtimeagent/internal/modules/identity/contracts"
)

type handler struct {
	microsoft contracts.Manager
	qqmail    contracts.QQMailManager
	sessions  identity.SessionAuthority
	mux       *http.ServeMux
}

func New(microsoft contracts.Manager, qqmail contracts.QQMailManager, sessions identity.SessionAuthority) (http.Handler, error) {
	if microsoft == nil || qqmail == nil || sessions == nil {
		return nil, contracts.ErrInvalid
	}
	h := &handler{microsoft: microsoft, qqmail: qqmail, sessions: sessions, mux: http.NewServeMux()}
	h.routes()
	return h, nil
}

func (h *handler) routes() {
	h.mux.HandleFunc("GET /oauth/microsoft/owner-start", h.ownerStart)
	h.mux.HandleFunc("GET /qq-mail/owner-start", h.ownerStart)
	h.mux.HandleFunc("POST /api/v1/owner/session", h.establishSession)
	h.mux.HandleFunc("GET /oauth/microsoft/start", h.start)
	h.mux.HandleFunc("GET /oauth/microsoft/callback", h.callback)
	h.mux.HandleFunc("GET /qq-mail/connect", h.connectPage)
	h.mux.HandleFunc("POST /api/v1/connections/qq-mail", h.connectMail)
	for _, provider := range []string{"microsoft", "qq-mail"} {
		h.mux.HandleFunc("GET /api/v1/connections/"+provider, h.list)
		h.mux.HandleFunc("GET /api/v1/connections/"+provider+"/status", h.status)
	}
	h.mux.HandleFunc("POST /api/v1/oauth/microsoft/disconnect", h.disconnect)
	h.mux.HandleFunc("POST /api/v1/connections/qq-mail/disconnect", h.disconnect)
}

func (h *handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	secure(w)
	if !loopback(r) {
		writeError(w, http.StatusNotFound)
		return
	}
	if r.URL.Path != "/oauth/microsoft/callback" && !sameOrigin(r) {
		writeError(w, http.StatusForbidden)
		return
	}
	h.mux.ServeHTTP(w, r)
}

func writeError(w http.ResponseWriter, status int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = io.WriteString(w, `{"detail":"request could not be completed","status":`+strconv.Itoa(status)+`}`)
}

// interface{} is confined to JSON codecs; requests and module ports are typed.
func writeJSON(w http.ResponseWriter, value interface{}) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(value)
}

func decode(r *http.Request, target interface{}) error {
	if r.Header.Get("Content-Type") != "application/json" {
		return contracts.ErrInvalid
	}
	data, err := io.ReadAll(io.LimitReader(r.Body, 8193))
	if err != nil || len(data) > 8192 {
		return contracts.ErrInvalid
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil || decoder.Decode(new(json.RawMessage)) != io.EOF {
		return contracts.ErrInvalid
	}
	return nil
}

func errorStatus(err error) int {
	switch {
	case errors.Is(err, identity.ErrForbidden):
		return http.StatusForbidden
	case errors.Is(err, identity.ErrSecurity):
		return http.StatusUnauthorized
	case errors.Is(err, contracts.ErrSecurity):
		return http.StatusUnauthorized
	case errors.Is(err, contracts.ErrInvalid):
		return http.StatusUnprocessableEntity
	case errors.Is(err, contracts.ErrConflict):
		return http.StatusConflict
	case errors.Is(err, contracts.ErrNotFound):
		return http.StatusNotFound
	}
	var provider contracts.ProviderError
	if errors.As(err, &provider) && provider.Class == "Authentication" {
		return http.StatusUnauthorized
	}
	return http.StatusServiceUnavailable
}
