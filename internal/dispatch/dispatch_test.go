package dispatch

import (
	"os"
	"testing"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "dispatch-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

// ── Send / Poll ───────────────────────────────────────────────────────────────

func TestSendAndPoll(t *testing.T) {
	err := Send("scheduler", "orchestrator", TypeTaskUnblocked, "plan1", "task1", "run1",
		map[string]string{"title": "Add tests"})
	if err != nil {
		t.Fatalf("Send: %v", err)
	}

	msgs, err := Poll("orchestrator")
	if err != nil {
		t.Fatalf("Poll: %v", err)
	}
	if len(msgs) == 0 {
		t.Fatal("expected at least one message, got 0")
	}

	m := msgs[0]
	if m.FromActor != "scheduler" {
		t.Errorf("FromActor: want 'scheduler', got %q", m.FromActor)
	}
	if m.ToActor != "orchestrator" {
		t.Errorf("ToActor: want 'orchestrator', got %q", m.ToActor)
	}
	if m.Type != TypeTaskUnblocked {
		t.Errorf("Type: want %q, got %q", TypeTaskUnblocked, m.Type)
	}
	if m.PlanID != "plan1" {
		t.Errorf("PlanID: want 'plan1', got %q", m.PlanID)
	}
	if m.TaskID != "task1" {
		t.Errorf("TaskID: want 'task1', got %q", m.TaskID)
	}
	if m.RunID != "run1" {
		t.Errorf("RunID: want 'run1', got %q", m.RunID)
	}
	if m.Delivered {
		t.Error("message should not be delivered yet")
	}
	if m.PayloadJSON == "" || m.PayloadJSON == "{}" {
		// We sent {"title":"Add tests"} so payload should contain it
		// PayloadJSON might be non-trivially populated
	}
}

func TestPollOnlyUndelivered(t *testing.T) {
	// Send two messages to "alice".
	if err := Send("a", "alice", TypeRequestReview, "", "t1", "", nil); err != nil {
		t.Fatalf("Send 1: %v", err)
	}
	if err := Send("b", "alice", TypeReviewResult, "", "t2", "", nil); err != nil {
		t.Fatalf("Send 2: %v", err)
	}

	msgs, err := Poll("alice")
	if err != nil {
		t.Fatalf("Poll: %v", err)
	}
	if len(msgs) < 2 {
		t.Fatalf("want >= 2 messages, got %d", len(msgs))
	}

	// Mark the first one delivered.
	firstID := msgs[0].ID
	if err := MarkDelivered(firstID); err != nil {
		t.Fatalf("MarkDelivered: %v", err)
	}

	// Poll again — should return only the undelivered message.
	remaining, err := Poll("alice")
	if err != nil {
		t.Fatalf("Poll after deliver: %v", err)
	}
	for _, m := range remaining {
		if m.ID == firstID {
			t.Errorf("delivered message %q should not appear in Poll", firstID)
		}
	}
}

func TestPollWrongRecipientReturnsEmpty(t *testing.T) {
	if err := Send("x", "bob", TypeNeedInfo, "", "", "", nil); err != nil {
		t.Fatalf("Send: %v", err)
	}
	// Poll for "carol" — should not see bob's message.
	msgs, err := Poll("carol")
	if err != nil {
		t.Fatalf("Poll: %v", err)
	}
	for _, m := range msgs {
		if m.ToActor != "carol" {
			t.Errorf("Poll returned message addressed to %q, not 'carol'", m.ToActor)
		}
	}
}

func TestMarkDelivered(t *testing.T) {
	if err := Send("src", "dst", TypeTaskUnblocked, "", "", "", nil); err != nil {
		t.Fatalf("Send: %v", err)
	}

	msgs, _ := Poll("dst")
	if len(msgs) == 0 {
		t.Fatal("expected at least one message")
	}

	id := msgs[len(msgs)-1].ID
	if err := MarkDelivered(id); err != nil {
		t.Fatalf("MarkDelivered: %v", err)
	}

	// Verify it's gone from the undelivered set.
	after, _ := Poll("dst")
	for _, m := range after {
		if m.ID == id {
			t.Errorf("message %q should not appear after MarkDelivered", id)
		}
	}
}

func TestSendNilPayload(t *testing.T) {
	if err := Send("a", "b", TypeNeedInfo, "", "", "", nil); err != nil {
		t.Fatalf("Send with nil payload: %v", err)
	}
	msgs, err := Poll("b")
	if err != nil {
		t.Fatalf("Poll: %v", err)
	}
	found := false
	for _, m := range msgs {
		if m.FromActor == "a" && m.Type == TypeNeedInfo {
			found = true
			if m.PayloadJSON == "" {
				t.Error("PayloadJSON should not be empty even for nil payload")
			}
		}
	}
	if !found {
		t.Error("message with nil payload not found in Poll results")
	}
}

// ── Message type constants ────────────────────────────────────────────────────

func TestMessageTypeConstants(t *testing.T) {
	if TypeRequestReview != "REQUEST_REVIEW" {
		t.Errorf("TypeRequestReview = %q", TypeRequestReview)
	}
	if TypeReviewResult != "REVIEW_RESULT" {
		t.Errorf("TypeReviewResult = %q", TypeReviewResult)
	}
	if TypeNeedInfo != "NEED_INFO" {
		t.Errorf("TypeNeedInfo = %q", TypeNeedInfo)
	}
	if TypeTaskUnblocked != "TASK_UNBLOCKED" {
		t.Errorf("TypeTaskUnblocked = %q", TypeTaskUnblocked)
	}
}
