package bootstrap

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestUnsupportedRolesFailBeforeReadingConfiguration(t *testing.T) {
	for _, args := range [][]string{nil, {"worker"}, {"qq"}, {"unknown"}, {"web", "extra"}} {
		if Run(context.Background(), args) == nil {
			t.Fatal("unsupported role accepted")
		}
	}
}

func TestLoadConfigUsesSyntheticFileAndEnvironmentOverride(t *testing.T) {
	path := filepath.Join(t.TempDir(), "synthetic.settings")
	if err := os.WriteFile(path, []byte("APP_LISTEN_PORT=8123\nDATABASE_PASSWORD=synthetic-password\n"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("APP_LISTEN_PORT", "8456")
	c, err := LoadConfig(path)
	if err != nil || c.ListenPort != 8456 {
		t.Fatalf("environment override failed: %v", err)
	}
	if c.Database.Password.Reveal() != "synthetic-password" {
		t.Fatal("synthetic file missing")
	}
	if err := os.WriteFile(path, []byte("'synthetic-invalid"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfig(path); err == nil || strings.Contains(err.Error(), "synthetic-invalid") {
		t.Fatal("invalid file leaked value or was accepted")
	}
	if _, err := LoadConfig(filepath.Join(t.TempDir(), "absent")); err != nil {
		t.Fatal(err)
	}
}

func TestConfigCheckAndDatabaseRequirement(t *testing.T) {
	t.Chdir(t.TempDir())
	t.Setenv("DATABASE_PASSWORD", "")
	if err := Run(context.Background(), []string{"check-config"}); err != nil {
		t.Fatal(err)
	}
	if err := Run(context.Background(), []string{"web"}); err == nil {
		t.Fatal("missing database secret accepted")
	}
}

func TestServerLifecycleAndBindingFailure(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := serve(ctx, Config{ListenHost: "127.0.0.1", ListenPort: 0}, nil); err != nil {
		t.Fatal(err)
	}
	if err := serve(context.Background(), Config{ListenHost: "invalid host", ListenPort: 0}, nil); err == nil {
		t.Fatal("invalid binding accepted")
	}
}

func TestHealthcheckStatusAndConnectionFailures(t *testing.T) {
	for _, status := range []int{200, 503} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(status) }))
		_, value, err := net.SplitHostPort(server.Listener.Addr().String())
		if err != nil {
			t.Fatal(err)
		}
		port, _ := strconv.Atoi(value)
		err = checkLiveness(context.Background(), port)
		server.Close()
		if (err == nil) != (status == 200) {
			t.Fatal("bad liveness result")
		}
		if checkLiveness(context.Background(), port) == nil {
			t.Fatal("closed listener accepted")
		}
	}
}
