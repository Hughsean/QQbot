package contracts

import "context"

type Processing interface {
	MarkNormalized(context.Context, string) error
	MarkUnderstood(context.Context, string) error
	MarkProposed(context.Context, string) error
	MarkCompleted(context.Context, string) error
	MarkIgnored(context.Context, string) error
	MarkNeedsReview(context.Context, string) error
}

type ContentQuery interface {
	Content(context.Context, string) (ContentView, error)
}
type SourceQuery interface {
	Source(context.Context, string) (SourceView, error)
}
