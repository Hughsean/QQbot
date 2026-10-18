package bootstrap

import (
	"encoding/json"
	"net/url"
	"strings"
	"testing"
)

func TestConfigDefaultsWithoutReadingEnvironment(t *testing.T) {
	c, err := ParseConfig(map[string]string{})
	if err != nil {
		t.Fatal(err)
	}
	if c.Address() != "127.0.0.1:8000" || c.Dimensions != 1024 || !c.QQ.Sandbox {
		t.Fatal("defaults changed")
	}
	if c.requireDatabase() == nil {
		t.Fatal("missing password accepted")
	}
}

func TestConfigRejectsPublicOrMalformedEndpoints(t *testing.T) {
	cases := []map[string]string{
		{"APP_LISTEN_HOST": "0.0.0.0"}, {"DATABASE_HOST": "postgres"},
		{"OLLAMA_BASE_URL": "http://example.com"}, {"OLLAMA_BASE_URL": "http://localhost:11434"},
		{"OLLAMA_BASE_URL": "http://127.0.0.1:11434/path"}, {"OLLAMA_BASE_URL": "http://synthetic:x@127.0.0.1:11434"},
		{"APP_CONTAINER": "true"}, {"APP_CONTAINER": "invalid"}, {"APP_LISTEN_PORT": "0"},
		{"DATABASE_PORT": "70000"}, {"DEFAULT_TIMEZONE": "not-a-zone"},
		{"RAG_EMBEDDING_DIMENSIONS": "768"}, {"APP_LISTEN_PORT": "synthetic-secret"},
	}
	for _, values := range cases {
		if _, err := ParseConfig(values); err == nil {
			t.Errorf("unsafe config accepted: %v", values)
		}
	}
}

func TestContainerEndpointsMustMatchExactly(t *testing.T) {
	values := map[string]string{"APP_CONTAINER": "true", "APP_LISTEN_HOST": "0.0.0.0", "DATABASE_HOST": "postgres", "OLLAMA_BASE_URL": "http://ollama:11434"}
	if _, err := ParseConfig(values); err != nil {
		t.Fatal(err)
	}
	for key, value := range map[string]string{"DATABASE_PORT": "55432", "OLLAMA_BASE_URL": "http://ollama:11434/", "APP_LISTEN_HOST": "::"} {
		copy := make(map[string]string)
		for k, v := range values {
			copy[k] = v
		}
		copy[key] = value
		if _, err := ParseConfig(copy); err == nil {
			t.Errorf("accepted changed endpoint %s", key)
		}
	}
}

func TestConfigurationDoesNotExposeSecretInputs(t *testing.T) {
	c, err := ParseConfig(map[string]string{"DATABASE_PASSWORD": "synthetic-sensitive-password", "QQ_BOT_SECRET": "synthetic-sensitive-secret"})
	if err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(c)
	if strings.Contains(string(data), "synthetic-sensitive") {
		t.Fatal("config serialization leaks secret")
	}
	u, err := url.Parse(c.Database.ConnectionString())
	if err != nil {
		t.Fatal(err)
	}
	password, _ := u.User.Password()
	if password != "synthetic-sensitive-password" || u.Query().Get("timezone") != "UTC" {
		t.Fatal("bad DSN encoding")
	}
	if err := c.requireDatabase(); err != nil {
		t.Fatal(err)
	}
}
