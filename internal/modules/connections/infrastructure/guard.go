package infrastructure

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"qqtimeagent/internal/modules/connections/contracts"
	"qqtimeagent/internal/modules/connections/domain"
)

type Guard struct{ config *pgx.ConnConfig }

// Locks use a dedicated connection. Waiting locks must never consume the pool
// needed by the winner's repository/vault calls (which would deadlock the pool).
func NewGuard(pool *pgxpool.Pool) *Guard { return &Guard{config: pool.Config().ConnConfig.Copy()} }

func (g Guard) Run(ctx context.Context, provider domain.Provider, work func(context.Context) error) error {
	key := int64(788810021)
	if provider == domain.QQMail {
		key = 788810022
	} else if provider != domain.Microsoft {
		return contracts.ErrInvalid
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	conn, err := pgx.ConnectConfig(ctx, g.config)
	if err != nil {
		return contracts.ErrStorage
	}
	defer func() {
		cleanup, done := context.WithTimeout(context.Background(), 2*time.Second)
		defer done()
		_ = conn.Close(cleanup)
	}()
	if _, err := conn.Exec(ctx, "SELECT pg_advisory_lock($1)", key); err != nil {
		return contracts.ErrStorage
	}
	return work(ctx)
}
