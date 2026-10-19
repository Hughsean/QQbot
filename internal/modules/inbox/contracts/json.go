package contracts

import "encoding/json"

func (a Address) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Address     string  `json:"address"`
		DisplayName *string `json:"display_name"`
	}{a.Address, optional(a.DisplayName)})
}

func (a AttachmentMetadata) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Filename     *string `json:"filename"`
		ContentType  string  `json:"content_type"`
		DeclaredSize *int64  `json:"declared_size"`
	}{optional(a.Filename), a.ContentType, a.DeclaredSize})
}

func optional(value string) *string {
	if value == "" {
		return nil
	}
	return &value
}
