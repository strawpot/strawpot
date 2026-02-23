package storage

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	_ "modernc.org/sqlite"
)

var (
	once sync.Once
	db   *sql.DB
	dbErr error
)

// DBPath returns the path to the global SQLite database.
func DBPath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".loguetown", "db.sqlite")
}

// Get returns the singleton database connection, opening and migrating it on first call.
func Get() (*sql.DB, error) {
	once.Do(func() {
		path := DBPath()
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			dbErr = fmt.Errorf("create db dir: %w", err)
			return
		}

		conn, err := sql.Open("sqlite", path)
		if err != nil {
			dbErr = fmt.Errorf("open sqlite: %w", err)
			return
		}

		// SQLite performs best with a single connection for writes.
		conn.SetMaxOpenConns(1)

		if err := migrate(conn); err != nil {
			conn.Close()
			dbErr = fmt.Errorf("migrate: %w", err)
			return
		}

		db = conn
	})
	return db, dbErr
}

// MustGet returns the database or panics.
func MustGet() *sql.DB {
	d, err := Get()
	if err != nil {
		panic(err)
	}
	return d
}

// Open creates and migrates a database at an explicit path.
// Use this in tests instead of Get() to avoid singleton conflicts.
func Open(path string) (*sql.DB, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("create db dir: %w", err)
	}
	conn, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}
	conn.SetMaxOpenConns(1)
	if err := migrate(conn); err != nil {
		conn.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	return conn, nil
}

func migrate(db *sql.DB) error {
	var version int
	_ = db.QueryRow("PRAGMA user_version").Scan(&version)

	if version == 0 {
		if _, err := db.Exec(createTablesSQL); err != nil {
			return fmt.Errorf("create tables: %w", err)
		}
		version = 1
		if _, err := db.Exec(fmt.Sprintf("PRAGMA user_version = %d", version)); err != nil {
			return fmt.Errorf("set schema version: %w", err)
		}
	}
	if version < 2 {
		// Add embedding/content columns to skill_files and memory_chunks.
		for _, stmt := range []string{
			"ALTER TABLE skill_files   ADD COLUMN embedding     BLOB",
			"ALTER TABLE skill_files   ADD COLUMN content_hash  TEXT",
			"ALTER TABLE memory_chunks ADD COLUMN embedding     BLOB",
			"ALTER TABLE memory_chunks ADD COLUMN content       TEXT",
		} {
			if _, err := db.Exec(stmt); err != nil {
				return fmt.Errorf("migrate v2 (%s): %w", stmt, err)
			}
		}
		if _, err := db.Exec("PRAGMA user_version = 2"); err != nil {
			return fmt.Errorf("set schema version 2: %w", err)
		}
	}
	return nil
}
