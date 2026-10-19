package httpaccounts

import (
	_ "embed"
	"html/template"
	"log/slog"
	"net/http"

	"qqtimeagent/internal/platform/secret"
)

//go:embed qqmail.html
var mailPage string

func (h *handler) connectPage(w http.ResponseWriter, r *http.Request) {
	if _, err := h.authenticate(r); err != nil {
		writeError(w, errorStatus(err))
		return
	}
	csrf, nonce := randomToken(), randomToken()
	setCookie(w, csrfCookie, csrf, false)
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; script-src 'nonce-"+nonce+"'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
	page, err := template.New("qqmail").Parse(mailPage)
	if err != nil {
		writeError(w, http.StatusServiceUnavailable)
		return
	}
	_ = page.Execute(w, struct{ CSRF, Nonce string }{CSRF: csrf, Nonce: nonce})
}

type connectRequest struct {
	Address string `json:"address"`
	Code    string `json:"authorization_code"`
}

func (connectRequest) String() string       { return "QQMailConnect([REDACTED])" }
func (connectRequest) GoString() string     { return "QQMailConnect([REDACTED])" }
func (connectRequest) LogValue() slog.Value { return slog.StringValue("QQMailConnect([REDACTED])") }

func (h *handler) connectMail(w http.ResponseWriter, r *http.Request) {
	owner, err := h.authenticate(r)
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	if !csrf(r) {
		writeError(w, http.StatusForbidden)
		return
	}
	var request connectRequest
	if decode(r, &request) != nil || request.Address == "" || request.Code == "" {
		writeError(w, http.StatusUnprocessableEntity)
		return
	}
	view, err := h.qqmail.Connect(r.Context(), owner.UserID, secret.New(request.Address), secret.New(request.Code))
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	writeJSON(w, view)
}
