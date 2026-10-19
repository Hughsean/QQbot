package domain

import (
	"time"

	"qqtimeagent/internal/modules/identity/contracts"
)

func Validate(p contracts.Preferences) error {
	if p.UserID != "owner" || p.Timezone == "" {
		return contracts.ErrInvalid
	}
	if _, err := time.LoadLocation(p.Timezone); err != nil {
		return contracts.ErrInvalid
	}
	if !validWindows(p) || !validWeekdays(p.WorkingWeekdays) {
		return contracts.ErrInvalid
	}
	if p.DefaultEventMinutes < 1 || p.DefaultTaskMinutes < 1 {
		return contracts.ErrInvalid
	}
	if p.QuietHoursEnabled && p.QuietStart == p.QuietEnd {
		return contracts.ErrInvalid
	}
	return nil
}

func validWindows(p contracts.Preferences) bool {
	for _, value := range []contracts.LocalTime{p.WorkStart, p.WorkEnd, p.LunchStart, p.LunchEnd, p.DigestLocalTime, p.QuietStart, p.QuietEnd} {
		if value < 0 || value >= 24*60*60*1000000 {
			return false
		}
	}
	return p.WorkStart < p.WorkEnd && p.WorkStart <= p.LunchStart && p.LunchStart < p.LunchEnd && p.LunchEnd <= p.WorkEnd
}

func validWeekdays(days []int32) bool {
	if len(days) == 0 || len(days) > 7 {
		return false
	}
	seen := make(map[int32]bool, 7)
	for _, day := range days {
		if day < 0 || day > 6 || seen[day] {
			return false
		}
		seen[day] = true
	}
	return true
}
