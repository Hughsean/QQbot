package contracts

import (
	"errors"
	"log/slog"
	"time"
)

var (
	ErrInvalid  = errors.New("invalid Inbox request")
	ErrNotFound = errors.New("inbox item does not exist")
	ErrConflict = errors.New("inbox version or identity conflict")
	ErrDeleted  = errors.New("inbox source is deleted or blocked")
	ErrStorage  = errors.New("inbox persistence failed")
)

type Address struct {
	Address     string `json:"address"`
	DisplayName string `json:"display_name"`
}
type AttachmentMetadata struct {
	Filename     string `json:"filename"`
	ContentType  string `json:"content_type"`
	DeclaredSize *int64 `json:"declared_size"`
}

// MailChange contains Provider-independent values; cursor and SDK DTOs stay outside it.
type MailChange struct {
	ExternalID, ThreadID, InternetMessageID, ChangeKey, DedupeKey string
	Sender                                                        Address
	Recipients                                                    []Address
	Subject, Body, ContentType                                    string
	OccurredAt                                                    time.Time
	HasAttachments                                                bool
	Attachments                                                   []AttachmentMetadata
}

type RawContent struct {
	Subject, BodyText, BodyHTML, MIMEType string
	Recipients                            []Address
	InternetMessageID, ChangeKey          string
	HasAttachments                        bool
	Attachments                           []AttachmentMetadata
}

type IngestResult struct {
	ID                string
	Created           bool
	Status, SourceRef string
}
type ContentView struct {
	ID, Subject, BodyText, BodyHTML, MIMEType, SourceRef, ContentHash string
	OccurredAt                                                        time.Time
}
type SourceView struct {
	ID, SourceType, ExternalID, ThreadID, SenderMask, Subject, Status, SourceRef string
	OccurredAt                                                                   time.Time
	Deleted                                                                      bool
}

func (MailChange) String() string        { return "MailChange([REDACTED])" }
func (MailChange) GoString() string      { return "MailChange([REDACTED])" }
func (MailChange) LogValue() slog.Value  { return slog.StringValue("MailChange([REDACTED])") }
func (RawContent) String() string        { return "RawContent([REDACTED])" }
func (RawContent) GoString() string      { return "RawContent([REDACTED])" }
func (RawContent) LogValue() slog.Value  { return slog.StringValue("RawContent([REDACTED])") }
func (ContentView) String() string       { return "InboxContent([REDACTED])" }
func (ContentView) GoString() string     { return "InboxContent([REDACTED])" }
func (ContentView) LogValue() slog.Value { return slog.StringValue("InboxContent([REDACTED])") }
