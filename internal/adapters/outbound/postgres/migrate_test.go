package postgres

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"
)

func TestSQLBaselineTracksFrozenSourceAndContainsNoDataBackfills(t *testing.T) {
	manifestData, err := migrations.ReadFile("migrations/baseline.json")
	if err != nil {
		t.Fatal(err)
	}
	var manifest struct {
		SourceCommit string `json:"source_commit"`
		SourceSHA    string `json:"source_sha256"`
		SQLSHA       string `json:"sql_sha256"`
		TableCount   int    `json:"table_count"`
	}
	if json.Unmarshal(manifestData, &manifest) != nil || manifest.SourceCommit == "" {
		t.Fatal("invalid baseline origin manifest")
	}
	sql, err := migrations.ReadFile("migrations/0001_initial_schema.sql")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(sql), "source SHA256: "+manifest.SourceSHA) {
		t.Fatal("Go schema baseline drifted from frozen Python source")
	}
	digest := sha256.Sum256(sql)
	if hex.EncodeToString(digest[:]) != manifest.SQLSHA {
		t.Fatal("SQL baseline checksum drifted")
	}
	if strings.Count(string(sql), "CREATE TABLE ") != manifest.TableCount {
		t.Fatal("baseline table inventory changed")
	}
	if strings.Contains(string(sql), "UPDATE ") || strings.Contains(string(sql), "DELETE FROM ") || strings.Contains(string(sql), "DROP TABLE") {
		t.Fatal("data backfill or destructive DDL in initial baseline")
	}
}
