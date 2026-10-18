package contracts

import "context"

type Message struct {
	Content  string
	ReplyTo  string
	Sequence uint32
}

type Sender interface {
	Send(context.Context, Message) (string, error)
}
