package infrastructure

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"qqtimeagent/internal/modules/identity/application"
	"qqtimeagent/internal/modules/identity/contracts"
)

type Repository struct{ Pool *pgxpool.Pool }

func (r Repository) Preferences(ctx context.Context, user string) (contracts.Preferences, error) {
	var p contracts.Preferences
	var start, end, lunchStart, lunchEnd, digest, quietStart, quietEnd pgtype.Time
	err := r.Pool.QueryRow(ctx, `SELECT user_id,timezone,work_start,work_end,lunch_start,lunch_end,working_weekdays,
		default_event_minutes,default_task_minutes,digest_enabled,digest_local_time,conflict_notifications_enabled,
		reauth_notifications_enabled,quiet_hours_enabled,quiet_start,quiet_end FROM identity_user_preferences WHERE user_id=$1`, user).
		Scan(&p.UserID, &p.Timezone, &start, &end, &lunchStart, &lunchEnd, &p.WorkingWeekdays, &p.DefaultEventMinutes, &p.DefaultTaskMinutes,
			&p.DigestEnabled, &digest, &p.ConflictNotificationsEnabled, &p.ReauthNotificationsEnabled, &p.QuietHoursEnabled, &quietStart, &quietEnd)
	if errors.Is(err, pgx.ErrNoRows) {
		return p, contracts.ErrNotFound
	}
	if err != nil {
		return p, contracts.ErrStorage
	}
	p.WorkStart, p.WorkEnd, p.LunchStart, p.LunchEnd = contracts.LocalTime(start.Microseconds), contracts.LocalTime(end.Microseconds), contracts.LocalTime(lunchStart.Microseconds), contracts.LocalTime(lunchEnd.Microseconds)
	p.DigestLocalTime, p.QuietStart, p.QuietEnd = contracts.LocalTime(digest.Microseconds), contracts.LocalTime(quietStart.Microseconds), contracts.LocalTime(quietEnd.Microseconds)
	return p, nil
}

func (r Repository) Initialize(ctx context.Context, p contracts.Preferences) (contracts.Preferences, error) {
	_, err := r.Pool.Exec(ctx, `INSERT INTO identity_user_preferences
		(user_id,timezone,work_start,work_end,lunch_start,lunch_end,working_weekdays,default_event_minutes,default_task_minutes,
		digest_enabled,digest_local_time,conflict_notifications_enabled,reauth_notifications_enabled,quiet_hours_enabled,quiet_start,quiet_end)
		VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) ON CONFLICT(user_id) DO NOTHING`,
		p.UserID, p.Timezone, localTime(p.WorkStart), localTime(p.WorkEnd), localTime(p.LunchStart), localTime(p.LunchEnd), p.WorkingWeekdays,
		p.DefaultEventMinutes, p.DefaultTaskMinutes, p.DigestEnabled, localTime(p.DigestLocalTime), p.ConflictNotificationsEnabled, p.ReauthNotificationsEnabled,
		p.QuietHoursEnabled, localTime(p.QuietStart), localTime(p.QuietEnd))
	if err != nil {
		return contracts.Preferences{}, contracts.ErrStorage
	}
	return r.Preferences(ctx, p.UserID)
}

func localTime(value contracts.LocalTime) pgtype.Time {
	return pgtype.Time{Microseconds: int64(value), Valid: true}
}

var _ application.Repository = Repository{}
