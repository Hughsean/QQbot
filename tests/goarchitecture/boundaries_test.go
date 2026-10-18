package goarchitecture

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
)

func repositoryRoot() string {
	_, path, _, _ := runtime.Caller(0)
	return filepath.Clean(filepath.Join(filepath.Dir(path), "../.."))
}

func TestProductionBoundariesSizeAndComplexity(t *testing.T) {
	root := repositoryRoot()
	for _, directory := range []string{"cmd", "internal"} {
		err := filepath.WalkDir(filepath.Join(root, directory), func(path string, d fs.DirEntry, err error) error {
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
			checkSource(t, filepath.ToSlash(relative), string(data))
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
}

func checkSource(t *testing.T, path, source string) {
	t.Helper()
	file, err := parser.ParseFile(token.NewFileSet(), path, source, 0)
	if err != nil {
		t.Fatal(err)
	}
	lines := 0
	for _, line := range strings.Split(source, "\n") {
		if value := strings.TrimSpace(line); value != "" && !strings.HasPrefix(value, "//") {
			lines++
		}
	}
	if lines > 500 {
		t.Errorf("%s: %d logical lines exceeds 500", path, lines)
	}
	for _, imp := range file.Imports {
		name, _ := strconv.Unquote(imp.Path.Value)
		if violation := importViolation(path, name); violation != "" {
			t.Errorf("%s: %s: %s", path, name, violation)
		}
	}
	for _, declaration := range file.Decls {
		f, ok := declaration.(*ast.FuncDecl)
		if !ok || f.Body == nil {
			continue
		}
		if n := complexity(f.Body); n > 10 {
			t.Errorf("%s: %s complexity %d exceeds 10", path, f.Name, n)
		}
	}
	ast.Inspect(file, func(node ast.Node) bool {
		call, ok := node.(*ast.CallExpr)
		if !ok {
			return true
		}
		selector, ok := call.Fun.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		if strings.Contains(path, "internal/bootstrap/") {
			return true
		}
		if selector.Sel.Name == "Getenv" || selector.Sel.Name == "LookupEnv" || selector.Sel.Name == "Environ" {
			t.Errorf("%s: environment access outside Bootstrap", path)
		}
		if selector.Sel.Name == "Now" && path != "internal/platform/clock/clock.go" {
			if x, ok := selector.X.(*ast.Ident); ok && x.Name == "time" {
				t.Errorf("%s: wall-clock access without Clock port", path)
			}
		}
		return true
	})
}

func importViolation(path, imp string) string {
	if strings.Contains(imp, "tencent-connect/botgo") && !strings.HasPrefix(path, "internal/adapters/qq/") {
		return "Provider SDK escaped QQ Adapter"
	}
	if strings.Contains(imp, "godotenv") && !strings.HasPrefix(path, "internal/bootstrap/") {
		return "configuration outside Bootstrap"
	}
	if strings.Contains(path, "/domain/") && !domainImportAllowed(imp) {
		return "impure Domain dependency"
	}
	parts := strings.Split(path, "/")
	if len(parts) < 4 || parts[1] != "modules" {
		return ""
	}
	module := parts[2]
	if strings.HasPrefix(imp, "qqtimeagent/internal/bootstrap") || strings.HasPrefix(imp, "qqtimeagent/internal/adapters") {
		return "business module imports composition/Adapter"
	}
	if !strings.HasPrefix(imp, "qqtimeagent/internal/modules/") {
		return ""
	}
	target := strings.Split(strings.TrimPrefix(imp, "qqtimeagent/internal/modules/"), "/")
	if len(target) < 2 {
		return "module root is not a public contract"
	}
	if target[0] != module && target[1] != "contracts" {
		return "cross-module internal implementation import"
	}
	return ""
}

func domainImportAllowed(imp string) bool {
	for _, prefix := range []string{"net", "database", "github.com", "golang.org", "qqtimeagent/internal/bootstrap", "qqtimeagent/internal/adapters"} {
		if strings.HasPrefix(imp, prefix) {
			return false
		}
	}
	return true
}

func complexity(node ast.Node) int {
	n := 1
	ast.Inspect(node, func(node ast.Node) bool {
		switch node := node.(type) {
		case *ast.IfStmt, *ast.ForStmt, *ast.RangeStmt:
			n++
		case *ast.CaseClause:
			if node.List != nil {
				n++
			}
		case *ast.CommClause:
			if node.Comm != nil {
				n++
			}
		case *ast.BinaryExpr:
			if node.Op == token.LAND || node.Op == token.LOR {
				n++
			}
		}
		return true
	})
	return n
}

func TestImportRulesRejectRepresentativeViolations(t *testing.T) {
	for _, pair := range [][2]string{
		{"internal/modules/agenda/domain/entry.go", "net/http"},
		{"internal/modules/agent/application/loop.go", "qqtimeagent/internal/modules/agenda/infrastructure"},
		{"internal/modules/inbox/contracts/source.go", "github.com/tencent-connect/botgo/dto"},
		{"internal/modules/notifications/application/send.go", "qqtimeagent/internal/bootstrap"},
	} {
		if importViolation(pair[0], pair[1]) == "" {
			t.Fatalf("boundary violation accepted: %v", pair)
		}
	}
	if importViolation("internal/modules/actions/application/create.go", "qqtimeagent/internal/modules/agenda/contracts") != "" {
		t.Fatal("public contract rejected")
	}
}
