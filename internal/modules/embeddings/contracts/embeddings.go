package contracts

import "context"

type Batch struct {
	Model      string
	Dimensions int
	Vectors    [][]float32
}

type Port interface {
	Embed(context.Context, []string) (Batch, error)
	Check(context.Context) error
}
