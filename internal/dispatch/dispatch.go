// Package dispatch implements the agent-to-agent (A2A) message bus backed by the
// messages SQLite table. Agents send typed envelopes; the scheduler and
// orchestrator poll for undelivered messages.
package dispatch

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/juhgiyo/loguetown/internal/storage"
)

// Message type constants for typed A2A envelopes.
const (
	TypeRequestReview = "REQUEST_REVIEW"
	TypeReviewResult  = "REVIEW_RESULT"
	TypeNeedInfo      = "NEED_INFO"
	TypeTaskUnblocked = "TASK_UNBLOCKED"
)

// Message is a single A2A dispatch envelope stored in the messages table.
type Message struct {
	ID          string `json:"id"`
	PlanID      string `json:"plan_id,omitempty"`
	TaskID      string `json:"task_id,omitempty"`
	RunID       string `json:"run_id,omitempty"`
	FromActor   string `json:"from_actor"`
	ToActor     string `json:"to_actor"`
	Type        string `json:"type"`
	PayloadJSON string `json:"payload_json"`
	ReplyTo     string `json:"reply_to,omitempty"`
	Delivered   bool   `json:"delivered"`
	CreatedAt   string `json:"created_at"`
}

// Send inserts a new message into the dispatch queue.
// payload is JSON-marshalled; pass nil for an empty payload.
func Send(from, to, msgType, planID, taskID, runID string, payload interface{}) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}

	payloadBytes := []byte("{}")
	if payload != nil {
		if b, e := json.Marshal(payload); e == nil {
			payloadBytes = b
		}
	}

	now := time.Now().UTC().Format(time.RFC3339)
	id := uuid.New().String()
	_, err = db.Exec(
		`INSERT INTO messages (id, plan_id, task_id, run_id, from_actor, to_actor, type, payload_json, delivered, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)`,
		id, nullStr(planID), nullStr(taskID), nullStr(runID),
		from, to, msgType, string(payloadBytes), now,
	)
	return err
}

// Poll returns all undelivered messages addressed to toActor.
func Poll(toActor string) ([]Message, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(
		`SELECT id, COALESCE(plan_id,''), COALESCE(task_id,''), COALESCE(run_id,''),
		        from_actor, to_actor, type, payload_json, COALESCE(reply_to,''), delivered, created_at
		 FROM messages WHERE to_actor = ? AND delivered = 0 ORDER BY created_at ASC`, toActor,
	)
	if err != nil {
		return nil, fmt.Errorf("poll messages: %w", err)
	}
	defer rows.Close()

	var msgs []Message
	for rows.Next() {
		var m Message
		var delivered int
		if err := rows.Scan(
			&m.ID, &m.PlanID, &m.TaskID, &m.RunID,
			&m.FromActor, &m.ToActor, &m.Type, &m.PayloadJSON,
			&m.ReplyTo, &delivered, &m.CreatedAt,
		); err != nil {
			return nil, err
		}
		m.Delivered = delivered != 0
		msgs = append(msgs, m)
	}
	return msgs, rows.Err()
}

// MarkDelivered marks a message as delivered.
func MarkDelivered(id string) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec("UPDATE messages SET delivered = 1 WHERE id = ?", id)
	return err
}

func nullStr(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}
