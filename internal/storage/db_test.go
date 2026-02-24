package storage_test

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	"github.com/juhgiyo/loguetown/internal/storage"
)

func openTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.sqlite")
	db, err := storage.Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

func TestOpenCreatesSchema(t *testing.T) {
	db := openTestDB(t)

	tables := []string{
		"projects", "plans", "tasks", "runs", "artifacts",
		"messages", "memory_chunks", "skill_files",
		"conversations", "conversation_turns",
		"escalations", "chronicle",
	}
	for _, table := range tables {
		var name string
		err := db.QueryRow(
			"SELECT name FROM sqlite_master WHERE type='table' AND name=?", table,
		).Scan(&name)
		if err != nil {
			t.Errorf("table %q not found: %v", table, err)
		}
	}
}

func TestOpenCreatesDirectory(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "subdir", "nested", "test.sqlite")
	db, err := storage.Open(dbPath)
	if err != nil {
		t.Fatalf("Open with nested path: %v", err)
	}
	db.Close()

	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		t.Errorf("db file not created at %s", dbPath)
	}
}

func TestOpenSchemaVersion(t *testing.T) {
	db := openTestDB(t)

	var version int
	if err := db.QueryRow("PRAGMA user_version").Scan(&version); err != nil {
		t.Fatalf("query user_version: %v", err)
	}
	if version != storage.SchemaVersion {
		t.Errorf("schema version = %d, want %d", version, storage.SchemaVersion)
	}
}

func TestOpenIdempotent(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "idempotent.sqlite")

	db1, err := storage.Open(dbPath)
	if err != nil {
		t.Fatalf("first Open: %v", err)
	}
	defer db1.Close()

	db2, err := storage.Open(dbPath)
	if err != nil {
		t.Fatalf("second Open: %v", err)
	}
	defer db2.Close()

	// Both should be able to query tables without error.
	var count int
	err = db2.QueryRow("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").Scan(&count)
	if err != nil {
		t.Fatalf("query after second open: %v", err)
	}
	if count == 0 {
		t.Error("expected tables in db after second open")
	}
}

func TestDBPathDefault(t *testing.T) {
	home, _ := os.UserHomeDir()
	want := filepath.Join(home, ".loguetown", "db.sqlite")
	got := storage.DBPath()
	if got != want {
		t.Errorf("DBPath() = %q, want %q", got, want)
	}
}
