package infrastructure

import (
	"context"
	"time"

	"qqtimeagent/internal/modules/identity/contracts"
)

func (r Repository) Aliases(ctx context.Context, user string) ([]contracts.Alias, error) {
	rows, err := r.Pool.Query(ctx, `SELECT alias FROM identity_owner_group_aliases WHERE user_id=$1 ORDER BY alias`, user)
	if err != nil {
		return nil, contracts.ErrStorage
	}
	defer rows.Close()
	result := make([]contracts.Alias, 0)
	for rows.Next() {
		var value contracts.Alias
		if err := rows.Scan(&value.Value); err != nil {
			return nil, contracts.ErrStorage
		}
		result = append(result, value)
	}
	if rows.Err() != nil {
		return nil, contracts.ErrStorage
	}
	return result, nil
}

func (r Repository) AddAlias(ctx context.Context, user string, value contracts.Alias, normalized string, now time.Time) (contracts.Alias, error) {
	var result contracts.Alias
	err := r.Pool.QueryRow(ctx, `INSERT INTO identity_owner_group_aliases(user_id,normalized_alias,alias,created_at)
		VALUES($1,$2,$3,$4) ON CONFLICT(user_id,normalized_alias) DO UPDATE SET normalized_alias=excluded.normalized_alias RETURNING alias`,
		user, normalized, value.Value, now).Scan(&result.Value)
	if err != nil {
		return contracts.Alias{}, contracts.ErrStorage
	}
	return result, nil
}

func (r Repository) MailRules(ctx context.Context, user string) ([]contracts.MailRule, error) {
	rows, err := r.Pool.Query(ctx, `SELECT rule_id::text,match_field,pattern,action FROM identity_mail_rules WHERE user_id=$1 ORDER BY created_at,rule_id`, user)
	if err != nil {
		return nil, contracts.ErrStorage
	}
	defer rows.Close()
	result := make([]contracts.MailRule, 0)
	for rows.Next() {
		var value contracts.MailRule
		if err := rows.Scan(&value.ID, &value.Field, &value.Pattern, &value.Action); err != nil {
			return nil, contracts.ErrStorage
		}
		result = append(result, value)
	}
	if rows.Err() != nil {
		return nil, contracts.ErrStorage
	}
	return result, nil
}

func (r Repository) PutMailRule(ctx context.Context, user string, value contracts.MailRule, normalized string, now time.Time) (contracts.MailRule, error) {
	var result contracts.MailRule
	err := r.Pool.QueryRow(ctx, `INSERT INTO identity_mail_rules(rule_id,user_id,match_field,pattern,normalized_pattern,action,created_at)
		VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(user_id,match_field,normalized_pattern) DO UPDATE SET
		pattern=excluded.pattern,action=excluded.action,created_at=excluded.created_at RETURNING rule_id::text,match_field,pattern,action`,
		value.ID, user, value.Field, value.Pattern, normalized, value.Action, now).Scan(&result.ID, &result.Field, &result.Pattern, &result.Action)
	if err != nil {
		return contracts.MailRule{}, contracts.ErrStorage
	}
	return result, nil
}
