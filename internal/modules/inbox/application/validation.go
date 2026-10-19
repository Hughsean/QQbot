package application

import (
	"strings"
	"unicode/utf8"

	"qqtimeagent/internal/modules/inbox/contracts"
)

func validateMail(change contracts.MailChange) error {
	if len(change.Subject)+len(change.Body) > 8<<20 || len(change.Recipients) > 1000 || len(change.Attachments) > 1000 {
		return contracts.ErrInvalid
	}
	if err := validateMailFields(change); err != nil {
		return err
	}
	if err := validateRecipients(change.Recipients); err != nil {
		return err
	}
	for _, attachment := range change.Attachments {
		if err := validateAttachment(attachment); err != nil {
			return err
		}
	}
	return nil
}

func validateMailFields(change contracts.MailChange) error {
	for _, value := range []string{change.Subject, change.Body} {
		if !safeField(value, 8<<20) {
			return contracts.ErrInvalid
		}
	}
	if !safeField(change.InternetMessageID, 998) || !safeField(change.ChangeKey, 512) {
		return contracts.ErrInvalid
	}
	return nil
}

func validateRecipients(recipients []contracts.Address) error {
	for _, recipient := range recipients {
		if strings.TrimSpace(recipient.Address) == "" || !safeField(recipient.Address, 320) || !safeField(recipient.DisplayName, 320) {
			return contracts.ErrInvalid
		}
	}
	return nil
}

func validateAttachment(attachment contracts.AttachmentMetadata) error {
	if attachment.DeclaredSize != nil && *attachment.DeclaredSize < 0 {
		return contracts.ErrInvalid
	}
	if !safeField(attachment.Filename, 1024) || !safeField(attachment.ContentType, 255) {
		return contracts.ErrInvalid
	}
	return nil
}

func safeField(value string, limit int) bool {
	return utf8.ValidString(value) && !strings.ContainsRune(value, 0) && utf8.RuneCountInString(value) <= limit
}
