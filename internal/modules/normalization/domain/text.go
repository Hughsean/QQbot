// Package domain contains deterministic, Provider-independent text rules.
package domain

import (
	"html"
	"strings"
)

const Version = "mail-text-v1"
const MaxSubjectRunes = 2000
const MaxBodyRunes = 200000

func Normalize(subject, body string) (string, string) {
	return truncate(collapse(html.UnescapeString(subject)), MaxSubjectRunes), truncate(collapse(body), MaxBodyRunes)
}

func collapse(value string) string {
	// Python str.splitlines includes Unicode line boundaries and C0 separators.
	value = strings.ReplaceAll(value, "\r\n", "\n")
	lines := strings.FieldsFunc(value, func(r rune) bool {
		switch r {
		case '\n', '\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\u0085', '\u2028', '\u2029':
			return true
		default:
			return false
		}
	})
	var result []string
	for _, line := range lines {
		if line = horizontalSpace(strings.TrimSpace(line)); line != "" {
			result = append(result, line)
		}
	}
	return strings.Join(result, "\n")
}

func horizontalSpace(line string) string {
	var result strings.Builder
	space := false
	for _, r := range line {
		if r == ' ' || r == '\t' {
			if !space {
				result.WriteByte(' ')
			}
			space = true
		} else {
			result.WriteRune(r)
			space = false
		}
	}
	return result.String()
}

func truncate(value string, limit int) string {
	count := 0
	for index := range value {
		if count == limit {
			return value[:index]
		}
		count++
	}
	return value
}
