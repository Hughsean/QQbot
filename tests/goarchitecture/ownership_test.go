package goarchitecture

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
)

var tableAccess = regexp.MustCompile(`(?i)\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+"?([a-z][a-z0-9_]+)`)

func TestSQLTableOwnershipAndEffectPorts(t *testing.T) {
	root := repositoryRoot()
	err := filepath.WalkDir(filepath.Join(root, "internal"), func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		relative, _ := filepath.Rel(root, path)
		relative = filepath.ToSlash(relative)
		file, err := parser.ParseFile(token.NewFileSet(), path, data, 0)
		if err != nil {
			return err
		}
		for _, imp := range file.Imports {
			name, _ := strconv.Unquote(imp.Path.Value)
			if forbiddenEffectPort(relative, name) {
				t.Errorf("%s: unauthorized effect dependency %s", relative, name)
			}
		}
		ast.Inspect(file, func(node ast.Node) bool {
			literal, ok := node.(*ast.BasicLit)
			if !ok || literal.Kind != token.STRING {
				return true
			}
			text, _ := strconv.Unquote(literal.Value)
			for _, match := range tableAccess.FindAllStringSubmatch(text, -1) {
				if owner := tableOwner(strings.ToLower(match[1])); owner != "" && !ownsSQL(relative, owner) {
					t.Errorf("%s: cross-module table access %s", relative, match[1])
				}
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func tableOwner(table string) string {
	for _, module := range []string{"actions", "agenda", "agent", "ai_gateway", "audit", "connections", "credentials", "data_lifecycle", "identity", "inbox", "knowledge", "normalization", "notifications", "reminders", "scheduling", "task_projection", "understanding", "workflow"} {
		if strings.HasPrefix(table, module+"_") {
			return module
		}
	}
	if strings.HasPrefix(table, "platform_") {
		return "platform"
	}
	return ""
}

func ownsSQL(path, owner string) bool {
	if owner == "platform" {
		return strings.HasPrefix(path, "internal/adapters/outbound/postgres/")
	}
	return strings.HasPrefix(path, "internal/modules/"+owner+"/infrastructure/")
}

func forbiddenEffectPort(path, imp string) bool {
	parts := strings.Split(path, "/")
	if len(parts) < 4 || parts[1] != "modules" {
		return false
	}
	module := parts[2]
	if !strings.HasPrefix(imp, "qqtimeagent/internal/modules/") {
		return false
	}
	target := strings.Split(strings.TrimPrefix(imp, "qqtimeagent/internal/modules/"), "/")[0]
	switch module {
	case "ai_gateway", "understanding", "scheduling":
		return target == "actions" || target == "notifications" || target == "credentials" || target == "reminders"
	case "agent":
		return target == "agenda" || target == "actions" || target == "reminders" || target == "credentials"
	}
	return false
}

func TestOwnershipAndEffectRulesRejectBypasses(t *testing.T) {
	if ownsSQL("internal/modules/actions/infrastructure/repository.go", tableOwner("agenda_entries")) {
		t.Fatal("cross-module SQL allowed")
	}
	if !ownsSQL("internal/modules/agenda/infrastructure/repository.go", tableOwner("agenda_entries")) {
		t.Fatal("owner SQL rejected")
	}
	if !forbiddenEffectPort("internal/modules/agent/application/loop.go", "qqtimeagent/internal/modules/actions/contracts") {
		t.Fatal("Agent bypassed Calendar System")
	}
	if forbiddenEffectPort("internal/modules/actions/application/create.go", "qqtimeagent/internal/modules/agenda/contracts") {
		t.Fatal("Actions public command port rejected")
	}
}
