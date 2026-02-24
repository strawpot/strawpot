package conversation

import (
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/juhgiyo/loguetown/internal/storage"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "conversation-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

// ensureProject inserts a project row to satisfy FK constraints on conversations.
func ensureProject(t *testing.T, id string) {
	t.Helper()
	db, err := storage.Get()
	if err != nil {
		t.Fatalf("storage.Get: %v", err)
	}
	_, err = db.Exec(
		`INSERT OR IGNORE INTO projects (id, name, repo_path, default_branch, created_at)
		 VALUES (?, ?, ?, ?, ?)`,
		id, fmt.Sprintf("project-%s", id), "/tmp/test-repo", "main",
		time.Now().UTC().Format(time.RFC3339),
	)
	if err != nil {
		t.Fatalf("ensureProject %q: %v", id, err)
	}
}

// ── CreateConversation / GetConversation ──────────────────────────────────────

func TestCreateAndGetConversation(t *testing.T) {
	ensureProject(t, "p1")
	conv, err := CreateConversation("p1", "orchestrator", "My first chat")
	if err != nil {
		t.Fatalf("CreateConversation: %v", err)
	}
	if conv.ID == "" {
		t.Error("ID should be non-empty after creation")
	}
	if conv.ProjectID != "p1" {
		t.Errorf("ProjectID: want 'p1', got %q", conv.ProjectID)
	}
	if conv.Participant != "orchestrator" {
		t.Errorf("Participant: want 'orchestrator', got %q", conv.Participant)
	}
	if conv.Title != "My first chat" {
		t.Errorf("Title: want 'My first chat', got %q", conv.Title)
	}

	got, err := GetConversation(conv.ID)
	if err != nil {
		t.Fatalf("GetConversation: %v", err)
	}
	if got.ID != conv.ID {
		t.Errorf("ID mismatch: want %q, got %q", conv.ID, got.ID)
	}
	if got.Title != conv.Title {
		t.Errorf("Title mismatch: want %q, got %q", conv.Title, got.Title)
	}
}

func TestGetConversationNotFound(t *testing.T) {
	_, err := GetConversation("nonexistent-id")
	if err == nil {
		t.Error("expected error for missing conversation, got nil")
	}
}

// ── ListConversations ─────────────────────────────────────────────────────────

func TestListConversations(t *testing.T) {
	ensureProject(t, "p2")
	_, err := CreateConversation("p2", "orchestrator", "Chat A")
	if err != nil {
		t.Fatalf("CreateConversation A: %v", err)
	}
	_, err = CreateConversation("p2", "orchestrator", "Chat B")
	if err != nil {
		t.Fatalf("CreateConversation B: %v", err)
	}

	convs, err := ListConversations("p2")
	if err != nil {
		t.Fatalf("ListConversations: %v", err)
	}
	if len(convs) < 2 {
		t.Errorf("want at least 2 conversations, got %d", len(convs))
	}
}

func TestListConversationsEmptyProject(t *testing.T) {
	ensureProject(t, "p-empty")
	convs, err := ListConversations("p-empty")
	if err != nil {
		t.Fatalf("ListConversations: %v", err)
	}
	if len(convs) != 0 {
		t.Errorf("want 0 conversations for empty project, got %d", len(convs))
	}
}

// ── AddTurn / ListTurns ───────────────────────────────────────────────────────

func TestAddAndListTurns(t *testing.T) {
	ensureProject(t, "p3")
	conv, err := CreateConversation("p3", "orchestrator", "Turn test")
	if err != nil {
		t.Fatalf("CreateConversation: %v", err)
	}

	turn1, err := AddTurn(conv.ID, "user", "Hello orchestrator", "", "", "")
	if err != nil {
		t.Fatalf("AddTurn user: %v", err)
	}
	if turn1.ID == "" {
		t.Error("Turn ID should be non-empty")
	}
	if turn1.Role != "user" {
		t.Errorf("Role: want 'user', got %q", turn1.Role)
	}

	_, err = AddTurn(conv.ID, "assistant", "Hello! How can I help?", "", "", "")
	if err != nil {
		t.Fatalf("AddTurn assistant: %v", err)
	}

	turns, err := ListTurns(conv.ID)
	if err != nil {
		t.Fatalf("ListTurns: %v", err)
	}
	if len(turns) != 2 {
		t.Fatalf("want 2 turns, got %d", len(turns))
	}
	if turns[0].Role != "user" {
		t.Errorf("turns[0].Role: want 'user', got %q", turns[0].Role)
	}
	if turns[1].Role != "assistant" {
		t.Errorf("turns[1].Role: want 'assistant', got %q", turns[1].Role)
	}
}

func TestAddTurnUpdatesLastTurnAt(t *testing.T) {
	ensureProject(t, "p4")
	conv, _ := CreateConversation("p4", "orchestrator", "Timestamp test")

	before, _ := GetConversation(conv.ID)
	if before.LastTurnAt != "" {
		t.Errorf("LastTurnAt should be empty before any turns, got %q", before.LastTurnAt)
	}

	_, err := AddTurn(conv.ID, "user", "test message", "", "", "")
	if err != nil {
		t.Fatalf("AddTurn: %v", err)
	}

	after, err := GetConversation(conv.ID)
	if err != nil {
		t.Fatalf("GetConversation after turn: %v", err)
	}
	if after.LastTurnAt == "" {
		t.Error("LastTurnAt should be set after AddTurn")
	}
}

func TestAddTurnWithPlanID(t *testing.T) {
	ensureProject(t, "p5")
	conv, _ := CreateConversation("p5", "orchestrator", "Plan link test")

	turn, err := AddTurn(conv.ID, "assistant", "Plan created", "plan-123", "task-456", "run-789")
	if err != nil {
		t.Fatalf("AddTurn with IDs: %v", err)
	}
	if turn.PlanID != "plan-123" {
		t.Errorf("PlanID: want 'plan-123', got %q", turn.PlanID)
	}
	if turn.TaskID != "task-456" {
		t.Errorf("TaskID: want 'task-456', got %q", turn.TaskID)
	}
	if turn.RunID != "run-789" {
		t.Errorf("RunID: want 'run-789', got %q", turn.RunID)
	}

	turns, _ := ListTurns(conv.ID)
	if len(turns) != 1 {
		t.Fatalf("want 1 turn, got %d", len(turns))
	}
	if turns[0].PlanID != "plan-123" {
		t.Errorf("persisted PlanID: want 'plan-123', got %q", turns[0].PlanID)
	}
}

func TestListTurnsEmpty(t *testing.T) {
	ensureProject(t, "p6")
	conv, _ := CreateConversation("p6", "orchestrator", "Empty turns")
	turns, err := ListTurns(conv.ID)
	if err != nil {
		t.Fatalf("ListTurns: %v", err)
	}
	if len(turns) != 0 {
		t.Errorf("want 0 turns for new conversation, got %d", len(turns))
	}
}
