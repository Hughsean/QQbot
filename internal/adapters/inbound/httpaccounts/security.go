package httpaccounts

import (
	"crypto/hmac"
	"crypto/rand"
	"encoding/base64"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	identity "qqtimeagent/internal/modules/identity/contracts"
	"qqtimeagent/internal/platform/secret"
)

const ownerCookie = "qq_time_agent_owner"
const oauthCookie = "qq_time_agent_oauth"
const csrfCookie = "qq_time_agent_csrf"

func loopback(r *http.Request) bool {
	host := r.Host
	if strings.Contains(host, ":") {
		var err error
		host, _, err = net.SplitHostPort(host)
		if err != nil {
			return false
		}
	}
	return host == "localhost" || host == "127.0.0.1"
}

func sameOrigin(r *http.Request) bool {
	if r.Header.Get("Sec-Fetch-Site") == "cross-site" {
		return false
	}
	origin := r.Header.Get("Origin")
	return origin == "" || origin == "http://"+r.Host
}

func secure(w http.ResponseWriter) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("X-Frame-Options", "DENY")
}

func cookie(r *http.Request, name string) string {
	value, err := r.Cookie(name)
	if err != nil {
		return ""
	}
	return value.Value
}
func setCookie(w http.ResponseWriter, name, value string, httpOnly bool) {
	http.SetCookie(w, &http.Cookie{Name: name, Value: value, Path: "/", MaxAge: 900, HttpOnly: httpOnly, SameSite: http.SameSiteLaxMode})
}
func csrf(r *http.Request) bool {
	value, header := cookie(r, csrfCookie), r.Header.Get("X-CSRF-Token")
	return len(value) >= 16 && len(value) <= 128 && hmac.Equal([]byte(value), []byte(header)) && sameOrigin(r)
}

func (h *handler) authenticate(r *http.Request) (identity.Session, error) {
	return h.sessions.Verify(secret.New(sessionToken(r)))
}

func sessionToken(r *http.Request) string {
	token := r.Header.Get("X-Owner-Session")
	if token == "" {
		token = cookie(r, ownerCookie)
	}
	return token
}

func randomToken() string {
	value := make([]byte, 24)
	if _, err := rand.Read(value); err != nil {
		panic("secure random source unavailable")
	}
	return base64.RawURLEncoding.EncodeToString(value)
}

func (h *handler) ownerStart(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		writeError(w, http.StatusForbidden)
		return
	}
	if target := canonicalStart(r); target != "" {
		http.Redirect(w, r, target, http.StatusSeeOther)
		return
	}
	next := "/qq-mail/connect"
	if strings.HasPrefix(r.URL.Path, "/oauth/") {
		values, err := h.microsoft.Statuses(r.Context(), "owner", "MICROSOFT")
		if err != nil {
			writeError(w, http.StatusServiceUnavailable)
			return
		}
		next = "/oauth/microsoft/start"
		for _, value := range values {
			if value.Default && value.Status != "DISCONNECTED" {
				next += "?connection_id=" + url.QueryEscape(value.ID)
				break
			}
		}
	}
	token, err := h.sessions.Issue("owner", 15*time.Minute)
	if err != nil {
		writeError(w, http.StatusServiceUnavailable)
		return
	}
	setCookie(w, ownerCookie, token.Reveal(), true)
	http.Redirect(w, r, next, http.StatusSeeOther)
}

func canonicalStart(r *http.Request) string {
	host, port, err := net.SplitHostPort(r.Host)
	if err != nil {
		host = r.Host
	}
	if host != "127.0.0.1" {
		return ""
	}
	authority := "localhost"
	if port != "" {
		authority = net.JoinHostPort(authority, port)
	}
	return "http://" + authority + r.URL.Path
}
