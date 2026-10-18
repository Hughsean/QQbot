package goarchitecture

import (
	"encoding/json"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

func TestLegacyRuntimeIsAbsentAndBehaviorInventoryRetained(t *testing.T) {
	root := repositoryRoot()
	for _, relative := range []string{"pyproject.toml", "uv.lock", ".python-version", "alembic.ini", "start.sh", "ops/Restore-QQTimeAgent.ps1", "ops/Build-MigrationBundle.ps1"} {
		if _, err := os.Stat(filepath.Join(root, relative)); !os.IsNotExist(err) {
			t.Errorf("legacy runtime asset remains: %s", relative)
		}
	}
	for _, directory := range []string{"src", "tests", "alembic", "ops"} {
		err := filepath.WalkDir(filepath.Join(root, directory), func(path string, d fs.DirEntry, err error) error {
			if os.IsNotExist(err) {
				return nil
			}
			if err != nil {
				return err
			}
			if d.IsDir() && d.Name() == "__pycache__" {
				return filepath.SkipDir
			}
			if !d.IsDir() && strings.HasSuffix(path, ".py") {
				t.Errorf("legacy Python source remains: %s", path)
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	data, err := os.ReadFile(filepath.Join(root, "docs/go-legacy-test-inventory.json"))
	if err != nil {
		t.Fatal(err)
	}
	var inventory struct {
		SourceCommit string `json:"source_commit"`
		Count        int    `json:"static_test_count"`
		Tests        []struct {
			File string `json:"file"`
			Test string `json:"test"`
		} `json:"tests"`
	}
	if json.Unmarshal(data, &inventory) != nil || inventory.Count != 601 || len(inventory.Tests) != inventory.Count || inventory.SourceCommit == "" {
		t.Fatal("legacy behavior inventory was lost")
	}
}

func TestSourceSecretScanExcludesRealEnvironmentAndCaches(t *testing.T) {
	root := repositoryRoot()
	patterns := []*regexp.Regexp{
		regexp.MustCompile(`\bsk-` + `[A-Za-z0-9_-]{20,}\b`),
		regexp.MustCompile(`\bgh[pousr]_` + `[A-Za-z0-9]{20,}\b`),
		regexp.MustCompile(`-----BEGIN (?:RSA |EC |OPENSSH )?` + `PRIVATE KEY-----`),
	}
	for _, directory := range []string{"cmd", "internal", "tests/goarchitecture", "docs", "ops", ".github"} {
		err := filepath.WalkDir(filepath.Join(root, directory), func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() || strings.HasPrefix(d.Name(), ".env") {
				return nil
			}
			if filepath.Ext(path) != ".go" && filepath.Ext(path) != ".md" && filepath.Ext(path) != ".yaml" {
				return nil
			}
			data, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			for _, pattern := range patterns {
				if pattern.Match(data) {
					t.Errorf("possible secret in %s (value suppressed)", path)
				}
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
}
