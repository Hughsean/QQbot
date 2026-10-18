package postgres

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Probe struct{ Pool *pgxpool.Pool }

func (p Probe) Check(ctx context.Context) error {
	var vector, trgm bool
	err := p.Pool.QueryRow(ctx, `SELECT
		EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector'),
		EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm')`).Scan(&vector, &trgm)
	if err != nil || !vector || !trgm {
		return errors.New("database unavailable or extensions missing")
	}
	return nil
}
