package chronicle_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/juhgiyo/loguetown/internal/chronicle"
)

// TestMain sets HOME to a temp dir so that storage.Get() (called internally by
// Append/Query) initialises the SQLite singleton in an isolated directory.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "chronicle-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

func TestEmitPopulatesFields(t *testing.T) {
	e, err := chronicle.Emit("proj-emit", "human:user", "TEST_EVENT", map[string]interface{}{
		"foo": "bar",
	})
	if err != nil {
		t.Fatalf("Emit: %v", err)
	}
	if e.ID == "" {
		t.Error("expected non-empty ID")
	}
	if e.TS == "" {
		t.Error("expected non-empty TS")
	}
	if e.Type != "TEST_EVENT" {
		t.Errorf("Type = %q, want TEST_EVENT", e.Type)
	}
	if e.Actor != "human:user" {
		t.Errorf("Actor = %q, want human:user", e.Actor)
	}
}

func TestEmitAndQueryRoundtrip(t *testing.T) {
	projectID := "proj-roundtrip"
	_, err := chronicle.Emit(projectID, "agent:test", "ROUNDTRIP", map[string]interface{}{
		"key": "value",
	})
	if err != nil {
		t.Fatalf("Emit: %v", err)
	}

	events, err := chronicle.Query(chronicle.Filter{ProjectID: projectID})
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(events) == 0 {
		t.Fatal("expected at least 1 event")
	}

	got := events[len(events)-1]
	if got.Type != "ROUNDTRIP" {
		t.Errorf("Type = %q, want ROUNDTRIP", got.Type)
	}
	if got.Payload["key"] != "value" {
		t.Errorf("Payload[key] = %v, want value", got.Payload["key"])
	}
}

func TestAppendWritesJSONL(t *testing.T) {
	home := os.Getenv("HOME")
	projectID := "proj-jsonl"

	_, err := chronicle.Emit(projectID, "agent:test", "JSONL_EVENT", nil)
	if err != nil {
		t.Fatalf("Emit: %v", err)
	}

	jsonlPath := filepath.Join(home, ".loguetown", "data", "projects", projectID, "events.jsonl")
	data, err := os.ReadFile(jsonlPath)
	if err != nil {
		t.Fatalf("read events.jsonl: %v", err)
	}
	if len(data) == 0 {
		t.Error("events.jsonl is empty")
	}
}

func TestQueryByEventType(t *testing.T) {
	projectID := "proj-filter"
	for _, typ := range []string{"TYPE_A", "TYPE_B", "TYPE_A"} {
		if _, err := chronicle.Emit(projectID, "agent:test", typ, nil); err != nil {
			t.Fatalf("Emit %s: %v", typ, err)
		}
	}

	events, err := chronicle.Query(chronicle.Filter{ProjectID: projectID, EventType: "TYPE_A"})
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("expected 2 TYPE_A events, got %d", len(events))
	}
}

func TestQueryLimit(t *testing.T) {
	projectID := "proj-limit"
	for i := 0; i < 5; i++ {
		if _, err := chronicle.Emit(projectID, "agent:test", "LIMIT_EVENT", nil); err != nil {
			t.Fatalf("Emit %d: %v", i, err)
		}
	}

	events, err := chronicle.Query(chronicle.Filter{ProjectID: projectID, Limit: 3})
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(events) != 3 {
		t.Errorf("expected 3 events with Limit=3, got %d", len(events))
	}
}

func TestRecent(t *testing.T) {
	projectID := "proj-recent"
	for i := 0; i < 4; i++ {
		if _, err := chronicle.Emit(projectID, "agent:test", "RECENT_EVENT", nil); err != nil {
			t.Fatalf("Emit %d: %v", i, err)
		}
	}

	events, err := chronicle.Recent(projectID, 2)
	if err != nil {
		t.Fatalf("Recent: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("expected 2 events, got %d", len(events))
	}
}

func TestQueryByActor(t *testing.T) {
	projectID := "proj-actor"
	chronicle.Emit(projectID, "agent:alice", "EVENT", nil)
	chronicle.Emit(projectID, "agent:bob", "EVENT", nil)
	chronicle.Emit(projectID, "agent:alice", "EVENT", nil)

	events, err := chronicle.Query(chronicle.Filter{ProjectID: projectID, Actor: "agent:alice"})
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("expected 2 events for alice, got %d", len(events))
	}
}
