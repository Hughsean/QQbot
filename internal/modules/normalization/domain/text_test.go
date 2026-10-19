package domain

import (
	"strings"
	"testing"
	"unicode/utf8"
)

func TestTextNormalizationMatchesLegacyWhitespaceAndEntities(t *testing.T) {
	subject, body := Normalize("  Weekly   &amp; review  ", "\t Hello  world \r\n\n Friday\t17:00\vNext\fPage\x1cBoundary\x1dAgain\x1eEnd\u0085NEL\u2028LS\u2029PS\rCR")
	if subject != "Weekly & review" || body != "Hello world\nFriday 17:00\nNext\nPage\nBoundary\nAgain\nEnd\nNEL\nLS\nPS\nCR" {
		t.Fatalf("unexpected normalized text %q / %q", subject, body)
	}
	_, body = Normalize("", "\n \t\n")
	if body != "" {
		t.Fatal("blank lines survived")
	}
	_, body = Normalize("", "a\u00a0b")
	if body != "a\u00a0b" {
		t.Fatal("nonhorizontal Unicode whitespace changed")
	}
}

func TestNormalizationCapsUnicodeCharactersWithoutBreakingUTF8(t *testing.T) {
	subject, body := Normalize(strings.Repeat("会", MaxSubjectRunes+1), strings.Repeat("议", MaxBodyRunes+20))
	if !utf8.ValidString(subject) || !utf8.ValidString(body) || utf8.RuneCountInString(subject) != MaxSubjectRunes || utf8.RuneCountInString(body) != MaxBodyRunes {
		t.Fatal("Unicode cap changed")
	}
	if subject, body := Normalize("subject", "body"); subject != "subject" || body != "body" {
		t.Fatal("short text changed")
	}
}
