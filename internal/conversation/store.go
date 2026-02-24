// Package conversation provides CRUD access to the conversations and
// conversation_turns SQLite tables.
package conversation

import (
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/juhgiyo/loguetown/internal/storage"
)

// Conversation is a persistent chat session between a human and the orchestrator.
type Conversation struct {
	ID          string `json:"id"`
	ProjectID   string `json:"project_id"`
	Participant string `json:"participant"`
	Title       string `json:"title,omitempty"`
	CreatedAt   string `json:"created_at"`
	LastTurnAt  string `json:"last_turn_at,omitempty"`
}

// Turn is one message within a conversation.
type Turn struct {
	ID             string `json:"id"`
	ConversationID string `json:"conversation_id"`
	Role           string `json:"role"` // "user" | "assistant"
	Content        string `json:"content"`
	PlanID         string `json:"plan_id,omitempty"`
	TaskID         string `json:"task_id,omitempty"`
	RunID          string `json:"run_id,omitempty"`
	CreatedAt      string `json:"created_at"`
}

// CreateConversation inserts a new conversation record.
func CreateConversation(projectID, participant, title string) (*Conversation, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC().Format(time.RFC3339)
	c := &Conversation{
		ID:          uuid.New().String(),
		ProjectID:   projectID,
		Participant: participant,
		Title:       title,
		CreatedAt:   now,
	}
	_, err = db.Exec(
		`INSERT INTO conversations (id, project_id, participant, title, created_at)
		 VALUES (?, ?, ?, ?, ?)`,
		c.ID, c.ProjectID, c.Participant, nullStr(c.Title), c.CreatedAt,
	)
	return c, err
}

// GetConversation returns a conversation by ID.
func GetConversation(id string) (*Conversation, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	var c Conversation
	err = db.QueryRow(
		`SELECT id, project_id, participant, COALESCE(title,''), created_at, COALESCE(last_turn_at,'')
		 FROM conversations WHERE id = ?`, id,
	).Scan(&c.ID, &c.ProjectID, &c.Participant, &c.Title, &c.CreatedAt, &c.LastTurnAt)
	if err != nil {
		return nil, fmt.Errorf("get conversation %s: %w", id, err)
	}
	return &c, nil
}

// ListConversations returns all conversations for a project, newest first.
func ListConversations(projectID string) ([]Conversation, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(
		`SELECT id, project_id, participant, COALESCE(title,''), created_at, COALESCE(last_turn_at,'')
		 FROM conversations WHERE project_id = ? ORDER BY created_at DESC`, projectID,
	)
	if err != nil {
		return nil, fmt.Errorf("list conversations: %w", err)
	}
	defer rows.Close()

	var convs []Conversation
	for rows.Next() {
		var c Conversation
		if err := rows.Scan(&c.ID, &c.ProjectID, &c.Participant, &c.Title, &c.CreatedAt, &c.LastTurnAt); err != nil {
			return nil, err
		}
		convs = append(convs, c)
	}
	return convs, rows.Err()
}

// AddTurn appends a turn to a conversation and updates last_turn_at.
func AddTurn(convID, role, content, planID, taskID, runID string) (*Turn, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC().Format(time.RFC3339)
	t := &Turn{
		ID:             uuid.New().String(),
		ConversationID: convID,
		Role:           role,
		Content:        content,
		PlanID:         planID,
		TaskID:         taskID,
		RunID:          runID,
		CreatedAt:      now,
	}
	_, err = db.Exec(
		`INSERT INTO conversation_turns (id, conversation_id, role, content, plan_id, task_id, run_id, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		t.ID, t.ConversationID, t.Role, t.Content,
		nullStr(t.PlanID), nullStr(t.TaskID), nullStr(t.RunID), t.CreatedAt,
	)
	if err != nil {
		return nil, err
	}
	// Update last_turn_at on the conversation.
	_, _ = db.Exec(
		`UPDATE conversations SET last_turn_at = ? WHERE id = ?`, now, convID,
	)
	return t, nil
}

// ListTurns returns all turns for a conversation in chronological order.
func ListTurns(convID string) ([]Turn, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(
		`SELECT id, conversation_id, role, content,
		        COALESCE(plan_id,''), COALESCE(task_id,''), COALESCE(run_id,''), created_at
		 FROM conversation_turns WHERE conversation_id = ? ORDER BY created_at ASC`, convID,
	)
	if err != nil {
		return nil, fmt.Errorf("list turns: %w", err)
	}
	defer rows.Close()

	var turns []Turn
	for rows.Next() {
		var t Turn
		if err := rows.Scan(&t.ID, &t.ConversationID, &t.Role, &t.Content,
			&t.PlanID, &t.TaskID, &t.RunID, &t.CreatedAt); err != nil {
			return nil, err
		}
		turns = append(turns, t)
	}
	return turns, rows.Err()
}

func nullStr(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}
