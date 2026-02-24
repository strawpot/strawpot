// Package memory provides read/write access to memory_chunks stored in SQLite.
package memory

import (
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/juhgiyo/loguetown/internal/storage"
)

// Chunk is a single memory record stored in memory_chunks.
type Chunk struct {
	ID              string
	AgentName       string
	Layer           string // episodic | semantic_local | semantic_global | working
	ProjectID       string
	FilePath        string
	Title           string
	Content         string
	Status          string // proposed | approved | rejected
	RejectionReason string
	CreatedAt       string
}

// Save inserts a new Chunk. ID and CreatedAt are set automatically.
func Save(c *Chunk) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	c.ID = uuid.New().String()
	c.CreatedAt = time.Now().UTC().Format(time.RFC3339)
	if c.Status == "" {
		c.Status = "proposed"
	}

	_, err = db.Exec(
		`INSERT INTO memory_chunks
		 (id, agent_name, layer, project_id, file_path, title, content, status, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		c.ID,
		c.AgentName,
		c.Layer,
		nullStr(c.ProjectID),
		c.FilePath,
		nullStr(c.Title),
		nullStr(c.Content),
		c.Status,
		c.CreatedAt,
	)
	return err
}

// List returns chunks matching the given filters (empty string = no filter).
func List(layer, agentName, projectID, status string) ([]Chunk, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}

	query := `SELECT id, agent_name, layer, COALESCE(project_id,''),
	                 file_path, COALESCE(title,''), COALESCE(content,''),
	                 status, COALESCE(rejection_reason,''), created_at
	          FROM memory_chunks WHERE 1=1`
	var args []interface{}

	if layer != "" {
		query += " AND layer = ?"
		args = append(args, layer)
	}
	if agentName != "" {
		query += " AND agent_name = ?"
		args = append(args, agentName)
	}
	if projectID != "" {
		query += " AND project_id = ?"
		args = append(args, projectID)
	}
	if status != "" {
		query += " AND status = ?"
		args = append(args, status)
	}
	query += " ORDER BY created_at DESC"

	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("list memory_chunks: %w", err)
	}
	defer rows.Close()

	var chunks []Chunk
	for rows.Next() {
		var c Chunk
		if err := rows.Scan(
			&c.ID, &c.AgentName, &c.Layer, &c.ProjectID,
			&c.FilePath, &c.Title, &c.Content,
			&c.Status, &c.RejectionReason, &c.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan memory chunk: %w", err)
		}
		chunks = append(chunks, c)
	}
	return chunks, rows.Err()
}

// Get returns a single Chunk by ID.
func Get(id string) (*Chunk, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}

	var c Chunk
	err = db.QueryRow(
		`SELECT id, agent_name, layer, COALESCE(project_id,''),
		        file_path, COALESCE(title,''), COALESCE(content,''),
		        status, COALESCE(rejection_reason,''), created_at
		 FROM memory_chunks WHERE id = ?`,
		id,
	).Scan(
		&c.ID, &c.AgentName, &c.Layer, &c.ProjectID,
		&c.FilePath, &c.Title, &c.Content,
		&c.Status, &c.RejectionReason, &c.CreatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("get memory chunk %s: %w", id, err)
	}
	return &c, nil
}

// SetStatus updates the status (and optional rejection reason) of a Chunk.
func SetStatus(id, status, rejectionReason string) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec(
		"UPDATE memory_chunks SET status = ?, rejection_reason = ? WHERE id = ?",
		status, nullStr(rejectionReason), id,
	)
	return err
}

func nullStr(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}
