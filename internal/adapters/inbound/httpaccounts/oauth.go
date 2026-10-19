package httpaccounts

import (
	"io"
	"net/http"
	"net/url"
	"strings"

	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/platform/ids"
	"qqtimeagent/internal/platform/secret"
)

func (h *handler) establishSession(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, 4097))
	if err != nil || len(body) > 4096 {
		writeError(w, http.StatusRequestEntityTooLarge)
		return
	}
	form, err := url.ParseQuery(string(body))
	if err != nil || len(form["session"]) != 1 {
		writeError(w, http.StatusBadRequest)
		return
	}
	token := secret.New(form.Get("session"))
	if _, err := h.sessions.Verify(token); err != nil {
		writeError(w, errorStatus(err))
		return
	}
	next := form.Get("next")
	if next == "" {
		next = "/oauth/microsoft/start"
	}
	if next != "/oauth/microsoft/start" && next != "/qq-mail/connect" {
		writeError(w, http.StatusBadRequest)
		return
	}
	setCookie(w, ownerCookie, token.Reveal(), true)
	http.Redirect(w, r, next, http.StatusSeeOther)
}

func (h *handler) start(w http.ResponseWriter, r *http.Request) {
	owner, err := h.authenticate(r)
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	id := r.URL.Query().Get("connection_id")
	if id != "" && ids.Validate(id) != nil {
		writeError(w, http.StatusUnprocessableEntity)
		return
	}
	if r.URL.Query().Has("session") || r.URL.Query().Has("token") {
		writeError(w, http.StatusBadRequest)
		return
	}
	start, err := h.microsoft.Begin(r.Context(), owner.UserID, id)
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	// The redirect is a sensitive value; no access logger is installed here.
	setCookie(w, ownerCookie, sessionToken(r), true)
	setCookie(w, oauthCookie, start.BrowserSession.Reveal(), true)
	setCookie(w, csrfCookie, randomToken(), false)
	w.Header().Set("Location", start.URL.Reveal())
	w.WriteHeader(http.StatusFound)
}

func (h *handler) callback(w http.ResponseWriter, r *http.Request) {
	parameters := r.URL.Query()
	callback := contracts.Callback{State: secret.New(parameters.Get("state")), Code: secret.New(parameters.Get("code")), ErrorCode: parameters.Get("error")}
	_, err := h.microsoft.Complete(r.Context(), callback, secret.New(cookie(r, oauthCookie)))
	http.SetCookie(w, &http.Cookie{Name: oauthCookie, Path: "/", MaxAge: -1, HttpOnly: true, SameSite: http.SameSiteLaxMode})
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	if err != nil {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = io.WriteString(w, "Microsoft connection could not be completed. Return to QQ and try again.")
		return
	}
	_, _ = io.WriteString(w, "Microsoft connection is active. You may close this window.")
}

func (h *handler) connectionViews(r *http.Request) ([]contracts.View, error) {
	owner, err := h.authenticate(r)
	if err != nil {
		return nil, err
	}
	if strings.Contains(r.URL.Path, "/qq-mail") {
		return h.qqmail.Statuses(r.Context(), owner.UserID)
	}
	return h.microsoft.Statuses(r.Context(), owner.UserID, "MICROSOFT")
}

func (h *handler) list(w http.ResponseWriter, r *http.Request) {
	values, err := h.connectionViews(r)
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	writeJSON(w, values)
}

func (h *handler) status(w http.ResponseWriter, r *http.Request) {
	values, err := h.connectionViews(r)
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	for _, value := range values {
		if value.Default {
			writeJSON(w, value)
			return
		}
	}
	writeJSON(w, (*contracts.View)(nil))
}

type disconnectRequest struct {
	ID        string `json:"connection_id"`
	Confirmed *bool  `json:"confirmed"`
}

func (h *handler) disconnect(w http.ResponseWriter, r *http.Request) {
	owner, err := h.authenticate(r)
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	if !csrf(r) {
		writeError(w, http.StatusForbidden)
		return
	}
	var request disconnectRequest
	if decode(r, &request) != nil || ids.Validate(request.ID) != nil || request.Confirmed == nil {
		writeError(w, http.StatusUnprocessableEntity)
		return
	}
	if !*request.Confirmed {
		writeError(w, http.StatusConflict)
		return
	}
	var view contracts.View
	if strings.Contains(r.URL.Path, "/qq-mail/") {
		view, err = h.qqmail.Disconnect(r.Context(), owner.UserID, request.ID, true)
	} else {
		view, err = h.microsoft.Disconnect(r.Context(), owner.UserID, request.ID, true)
	}
	if err != nil {
		writeError(w, errorStatus(err))
		return
	}
	writeJSON(w, view)
}
