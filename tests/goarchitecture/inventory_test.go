package goarchitecture

import (
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLegacyRegressionMappingsReferenceExistingGoTests(t *testing.T) {
	root := repositoryRoot()
	data, err := os.ReadFile(filepath.Join(root, "docs/go-legacy-test-inventory.json"))
	if err != nil {
		t.Fatal(err)
	}
	var inventory struct {
		Tests []struct {
			File, Test, Status string
			GoTests            []string `json:"go_tests"`
		} `json:"tests"`
	}
	if err := json.Unmarshal(data, &inventory); err != nil {
		t.Fatal(err)
	}
	cache := make(map[string]map[string]bool)
	seen := make(map[string]bool)
	for _, scenario := range inventory.Tests {
		identity := scenario.File + "::" + scenario.Test
		if seen[identity] {
			t.Fatal("duplicate legacy scenario", identity)
		}
		seen[identity] = true
		if scenario.Status == "pending_go_mapping" {
			continue
		}
		if scenario.Status != "mapped_go_regression" || len(scenario.GoTests) == 0 {
			t.Fatal("invalid migration status or empty regression mapping", identity)
		}
		for _, target := range scenario.GoTests {
			path, name, ok := strings.Cut(target, ":")
			if !ok || !strings.HasSuffix(path, "_test.go") || (!strings.HasPrefix(path, "internal/") && !strings.HasPrefix(path, "tests/")) || strings.Contains(path, "..") {
				t.Fatal("invalid regression reference", target)
			}
			if cache[path] == nil {
				cache[path] = testDeclarations(t, filepath.Join(root, filepath.FromSlash(path)))
			}
			if !cache[path][name] {
				t.Fatal("mapped Go test is absent", target)
			}
		}
	}
}

func testDeclarations(t *testing.T, path string) map[string]bool {
	t.Helper()
	file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	result := make(map[string]bool)
	for _, declaration := range file.Decls {
		if function, ok := declaration.(*ast.FuncDecl); ok && strings.HasPrefix(function.Name.Name, "Test") {
			result[function.Name.Name] = true
		}
	}
	return result
}
