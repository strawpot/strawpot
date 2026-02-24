package chronicle

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"time"

	"github.com/google/uuid"
	"github.com/juhgiyo/loguetown/internal/storage"
)

// Event is a single Chronicle entry.
type Event struct {
	ID        string                 `json:"id"`
	TS        string                 `json:"ts"`
	ProjectID string                 `json:"project_id,omitempty"`
	PlanID    string                 `json:"plan_id,omitempty"`
	TaskID    string                 `json:"task_id,omitempty"`
	RunID     string                 `json:"run_id,omitempty"`
	Actor     string                 `json:"actor"`
	Type      string                 `json:"type"`
	Payload   map[string]interface{} `json:"payload"`
}

// Filter for querying Chronicle.
type Filter struct {
	ProjectID string
	PlanID    string
	TaskID    string
	RunID     string
	Actor     string
	EventType string
	Since     string
	Limit     int
}

// secretPatterns for log redaction.
var secretPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)("(?:password|secret|token|api_?key|auth|bearer|credential)[^"]*"\s*:\s*)"[^"]{4,}"`),
	regexp.MustCompile(`\b(sk-[A-Za-z0-9]{20,})\b`),
	regexp.MustCompile(`(?i)\b(Bearer\s+[A-Za-z0-9\-._~+/]+=*)\b`),
}

func redactSecrets(s string) string {
	for _, p := range secretPatterns {
		s = p.ReplaceAllStringFunc(s, func(m string) string {
			// Keep the key part (group 1) if present, replace value
			sub := p.FindStringSubmatch(m)
			if len(sub) > 1 && sub[1] != "" {
				return sub[1] + `"[REDACTED]"`
			}
			return "[REDACTED]"
		})
	}
	return s
}

// ChronicleDir returns the project-specific chronicle directory.
func ChronicleDir(projectID string) string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".loguetown", "data", "projects", projectID)
}

// Append writes an event to both the JSONL file and the SQLite index.
func Append(e Event) error {
	data, err := json.Marshal(e)
	if err != nil {
		return fmt.Errorf("marshal event: %w", err)
	}
	line := redactSecrets(string(data))

	// Write JSONL
	if e.ProjectID != "" {
		dir := ChronicleDir(e.ProjectID)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return fmt.Errorf("create chronicle dir: %w", err)
		}
		f, err := os.OpenFile(filepath.Join(dir, "events.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		if err != nil {
			return fmt.Errorf("open events.jsonl: %w", err)
		}
		_, werr := fmt.Fprintln(f, line)
		f.Close()
		if werr != nil {
			return fmt.Errorf("write events.jsonl: %w", werr)
		}
	}

	// Index in SQLite
	db, err := storage.Get()
	if err != nil {
		return fmt.Errorf("get db: %w", err)
	}

	payloadJSON := redactSecrets(string(mustMarshal(e.Payload)))

	_, err = db.Exec(
		`INSERT INTO chronicle (id, ts, project_id, plan_id, task_id, run_id, actor, event_type, payload_json)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		e.ID, e.TS,
		nullableStr(e.ProjectID), nullableStr(e.PlanID),
		nullableStr(e.TaskID), nullableStr(e.RunID),
		e.Actor, e.Type, payloadJSON,
	)
	return err
}

// Emit constructs an event with a new UUID + timestamp and appends it.
func Emit(projectID, actor, eventType string, payload map[string]interface{}) (Event, error) {
	e := Event{
		ID:        uuid.New().String(),
		TS:        time.Now().UTC().Format(time.RFC3339Nano),
		ProjectID: projectID,
		Actor:     actor,
		Type:      eventType,
		Payload:   payload,
	}
	return e, Append(e)
}

func nullableStr(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}

func mustMarshal(v interface{}) []byte {
	b, _ := json.Marshal(v)
	return b
}
