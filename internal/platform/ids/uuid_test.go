package ids

import "testing"

func TestUUIDCanonicalAndUnique(t *testing.T) {
	first, second := New(), New()
	if first == second || Validate(first) != nil || Validate(second) != nil || first[14] != '4' {
		t.Fatal("invalid generated UUID")
	}
	for _, value := range []string{"", "00000000000040008000000000000001", "00000000_0000-4000-8000-000000000001", "00000000-0000-4000-8000-00000000000G", "00000000-0000-4000-8000-00000000000A"} {
		if Validate(value) == nil {
			t.Fatal("noncanonical UUID accepted")
		}
	}
}
