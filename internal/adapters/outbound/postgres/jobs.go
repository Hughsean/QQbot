package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"qqtimeagent/internal/platform/jobs"
)

type JobQueue struct{ Pool *pgxpool.Pool }

func (q JobQueue) Enqueue(ctx context.Context, r jobs.Request) (string, error) {
	if r.ID == "" || strings.TrimSpace(r.Kind) == "" || strings.TrimSpace(r.IdempotencyKey) == "" ||
		r.AvailableAt.IsZero() || r.MaxAttempts < 1 || !json.Valid(r.Payload) || len(r.Payload) > 65536 {
		return "", errors.New("invalid job request")
	}
	var id string
	err := q.Pool.QueryRow(ctx, `INSERT INTO platform_jobs
		(job_id,kind,payload,status,idempotency_key,available_at,attempt_count,max_attempts,created_at,updated_at)
		VALUES ($1,$2,$3,'PENDING',$4,$5,0,$6,$5,$5)
		ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key=EXCLUDED.idempotency_key
		RETURNING job_id::text`, r.ID, r.Kind, r.Payload, r.IdempotencyKey, r.AvailableAt, r.MaxAttempts).Scan(&id)
	if err != nil {
		return "", errors.New("job enqueue failed")
	}
	return id, nil
}

// Kind allowlisting prevents a partially migrated Worker from claiming old jobs.
func (q JobQueue) LeaseDue(ctx context.Context, now time.Time, owner string, kinds []string, limit int, duration time.Duration) ([]jobs.Lease, error) {
	if err := validateLeaseRequest(now, owner, kinds, limit, duration); err != nil {
		return nil, err
	}
	rows, err := q.Pool.Query(ctx, `WITH due AS (
		SELECT job_id FROM platform_jobs WHERE kind=ANY($1) AND available_at<=$2
		AND (status IN ('PENDING','RETRY_WAIT') OR (status='LEASED' AND lease_until<$2))
		ORDER BY available_at,job_id FOR UPDATE SKIP LOCKED LIMIT $3
	) UPDATE platform_jobs j SET status='LEASED',lease_owner=$4,lease_until=$5,
		attempt_count=j.attempt_count+1,updated_at=$2
	FROM due WHERE j.job_id=due.job_id
	RETURNING j.job_id::text,j.kind,j.payload,j.attempt_count,j.max_attempts`, kinds, now, limit, owner, now.Add(duration))
	if err != nil {
		return nil, errors.New("job lease failed")
	}
	defer rows.Close()
	result := make([]jobs.Lease, 0)
	for rows.Next() {
		lease := jobs.Lease{Owner: owner}
		if rows.Scan(&lease.ID, &lease.Kind, &lease.Payload, &lease.Attempt, &lease.MaxAttempts) != nil {
			return nil, errors.New("invalid stored job")
		}
		result = append(result, lease)
	}
	if rows.Err() != nil {
		return nil, errors.New("job lease read failed")
	}
	return result, nil
}

func validateLeaseRequest(now time.Time, owner string, kinds []string, limit int, duration time.Duration) error {
	if now.IsZero() || owner == "" || len(kinds) == 0 || limit < 1 || limit > 1000 || duration <= 0 {
		return errors.New("invalid job lease request")
	}
	return nil
}

func (q JobQueue) Complete(ctx context.Context, lease jobs.Lease, now time.Time) error {
	return q.finish(ctx, lease, now, "COMPLETE", "", nil)
}

func (q JobQueue) Fail(ctx context.Context, lease jobs.Lease, now time.Time, class string, retry *time.Time) error {
	if class == "" || len(class) > 80 {
		return errors.New("invalid job failure class")
	}
	status := "RETRY_WAIT"
	if retry == nil || lease.Attempt >= lease.MaxAttempts {
		status, retry = "DEAD_LETTER", nil
	}
	return q.finish(ctx, lease, now, status, class, retry)
}

func (q JobQueue) finish(ctx context.Context, lease jobs.Lease, now time.Time, status, class string, retry *time.Time) error {
	if now.IsZero() {
		return errors.New("job finish time required")
	}
	result, err := q.Pool.Exec(ctx, `UPDATE platform_jobs SET status=$1,lease_owner=NULL,
		lease_until=NULL,last_error_class=NULLIF($2,''),available_at=COALESCE($3,available_at),updated_at=$4
		WHERE job_id=$5 AND status='LEASED' AND lease_owner=$6 AND attempt_count=$7 AND lease_until>$4`,
		status, class, retry, now, lease.ID, lease.Owner, lease.Attempt)
	if err != nil {
		return errors.New("job finish failed")
	}
	if result.RowsAffected() != 1 {
		return jobs.ErrStaleLease
	}
	return nil
}

var _ jobs.Queue = JobQueue{}
