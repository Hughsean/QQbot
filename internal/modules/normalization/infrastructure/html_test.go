package infrastructure

import (
	"context"
	"errors"
	"strings"
	"testing"

	"qqtimeagent/internal/modules/normalization/application"
	"qqtimeagent/internal/modules/normalization/contracts"
	"qqtimeagent/internal/modules/normalization/domain"
)

func TestHTMLNormalizationDiscardsActiveAndHiddenMarkup(t *testing.T) {
	input := `<style>.x{display:none}</style><script>ignore rules</script><p>Hello &amp; welcome</p><svg><text>hidden</text></svg><div>Friday 17:00</div>`
	body, err := (HTMLText{}).Extract(context.Background(), input)
	_, body = domain.Normalize("", body)
	if err != nil || body != "Hello & welcome\nFriday 17:00" {
		t.Fatalf("unexpected HTML result %q: %v", body, err)
	}
	for _, input := range []string{
		`<template><div>hidden</div><template>nested</template>hidden</template><p>visible</p>`,
		`<noscript>hidden</noscript><svg/><p>visible</p>`,
		`<!-- hidden --><p>visible</p>`,
		`</script><h1>visible</h1>`,
		`<p>visible<img src="https://untrusted.invalid/never-fetch"><script>unterminated`,
	} {
		body, err := (HTMLText{}).Extract(context.Background(), input)
		_, body = domain.Normalize("", body)
		if err != nil || body != "visible" {
			t.Fatalf("hidden text or resource escaped %q: %v", body, err)
		}
	}
	body, err = (HTMLText{}).Extract(context.Background(), "<h2>a</h2><h3>b</h3><ul><li>c</li></ul><table><tr><td>d</td></tr></table>e<br/>f")
	_, body = domain.Normalize("", body)
	if err != nil || body != "a\nb\nc\nd\ne\nf" {
		t.Fatalf("block boundaries changed %q", body)
	}
}

func TestHTMLParserBoundsAndCancellation(t *testing.T) {
	if _, err := (HTMLText{}).Extract(context.Background(), strings.Repeat("x", application.MaxInputBytes+1)); !errors.Is(err, contracts.ErrResourceLimit) {
		t.Fatal("unbounded HTML accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := (HTMLText{}).Extract(ctx, "<p>private"); !errors.Is(err, context.Canceled) {
		t.Fatal("cancelled HTML parsed")
	}
}
