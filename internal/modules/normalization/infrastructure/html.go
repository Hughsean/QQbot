package infrastructure

import (
	"context"
	"io"
	"strings"

	"golang.org/x/net/html"
	"qqtimeagent/internal/modules/normalization/application"
	"qqtimeagent/internal/modules/normalization/contracts"
)

// HTMLText extracts text without fetching resources or executing active markup.
type HTMLText struct{}

func (HTMLText) Extract(ctx context.Context, value string) (string, error) {
	if len(value) > application.MaxInputBytes {
		return "", contracts.ErrResourceLimit
	}
	parser := html.NewTokenizer(strings.NewReader(value))
	parser.SetMaxBuf(application.MaxInputBytes)
	var result strings.Builder
	ignored := 0
	for {
		if err := ctx.Err(); err != nil {
			return "", err
		}
		token := parser.Next()
		if token == html.ErrorToken {
			if parser.Err() != io.EOF {
				return "", contracts.ErrResourceLimit
			}
			return result.String(), nil
		}
		ignored = extractToken(parser, token, ignored, &result)
	}
}

func extractToken(parser *html.Tokenizer, token html.TokenType, ignored int, result *strings.Builder) int {
	if token == html.TextToken {
		if ignored == 0 {
			result.Write(parser.Text())
		}
		return ignored
	}
	name, _ := parser.TagName()
	tag := string(name)
	if token == html.SelfClosingTagToken {
		parser.NextIsNotRawText()
		if ignoredTag(tag) {
			return ignored
		}
	}
	if ignoredTag(tag) {
		if token == html.EndTagToken {
			return max(0, ignored-1)
		}
		return ignored + 1
	}
	if ignored == 0 && blockTag(tag, token) {
		result.WriteByte('\n')
	}
	return ignored
}

func ignoredTag(tag string) bool {
	switch tag {
	case "script", "style", "svg", "template", "noscript":
		return true
	default:
		return false
	}
}

func blockTag(tag string, token html.TokenType) bool {
	if token == html.EndTagToken {
		return tag == "p" || tag == "div" || tag == "li" || tag == "tr"
	}
	switch tag {
	case "br", "p", "div", "li", "tr", "h1", "h2", "h3":
		return true
	default:
		return false
	}
}
