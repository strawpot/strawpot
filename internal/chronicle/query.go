package chronicle

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/steveyegge/loguetown/internal/storage"
)

// Query returns events matching the filter.
func Query(f Filter) ([]Event, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}

	var conds []string
	var args []interface{}

	if f.ProjectID != "" {
		conds = append(conds, "project_id = ?")
		args = append(args, f.ProjectID)
	}
	if f.PlanID != "" {
		conds = append(conds, "plan_id = ?")
		args = append(args, f.PlanID)
	}
	if f.TaskID != "" {
		conds = append(conds, "task_id = ?")
		args = append(args, f.TaskID)
	}
	if f.RunID != "" {
		conds = append(conds, "run_id = ?")
		args = append(args, f.RunID)
	}
	if f.Actor != "" {
		conds = append(conds, "actor = ?")
		args = append(args, f.Actor)
	}
	if f.EventType != "" {
		conds = append(conds, "event_type = ?")
		args = append(args, f.EventType)
	}
	if f.Since != "" {
		conds = append(conds, "ts >= ?")
		args = append(args, f.Since)
	}

	where := ""
	if len(conds) > 0 {
		where = "WHERE " + strings.Join(conds, " AND ")
	}

	limit := ""
	if f.Limit > 0 {
		limit = fmt.Sprintf("LIMIT %d", f.Limit)
	}

	q := fmt.Sprintf("SELECT id, ts, COALESCE(project_id,''), COALESCE(plan_id,''), COALESCE(task_id,''), COALESCE(run_id,''), actor, event_type, COALESCE(payload_json,'{}') FROM chronicle %s ORDER BY ts ASC %s", where, limit)

	rows, err := db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var events []Event
	for rows.Next() {
		var e Event
		var payloadJSON string
		if err := rows.Scan(&e.ID, &e.TS, &e.ProjectID, &e.PlanID, &e.TaskID, &e.RunID, &e.Actor, &e.Type, &payloadJSON); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(payloadJSON), &e.Payload)
		events = append(events, e)
	}
	return events, rows.Err()
}

// Recent returns the last N events for a project (most recent last).
func Recent(projectID string, limit int) ([]Event, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}

	rows, err := db.Query(
		`SELECT id, ts, COALESCE(project_id,''), COALESCE(plan_id,''), COALESCE(task_id,''), COALESCE(run_id,''), actor, event_type, COALESCE(payload_json,'{}')
		 FROM chronicle WHERE project_id = ? ORDER BY ts DESC LIMIT ?`,
		projectID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var events []Event
	for rows.Next() {
		var e Event
		var payloadJSON string
		if err := rows.Scan(&e.ID, &e.TS, &e.ProjectID, &e.PlanID, &e.TaskID, &e.RunID, &e.Actor, &e.Type, &payloadJSON); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(payloadJSON), &e.Payload)
		events = append(events, e)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// Reverse to get chronological order
	for i, j := 0, len(events)-1; i < j; i, j = i+1, j-1 {
		events[i], events[j] = events[j], events[i]
	}
	return events, nil
}
