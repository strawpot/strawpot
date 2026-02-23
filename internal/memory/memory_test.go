package memory

import (
	"os"
	"testing"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "memory-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

func newChunk(agent, layer, title string) *Chunk {
	return &Chunk{
		AgentName: agent,
		Layer:     layer,
		FilePath:  "memory/" + agent + "/" + layer + ".md",
		Title:     title,
		Content:   "Some content for " + title,
	}
}

func TestSaveAndGet(t *testing.T) {
	c := newChunk("alice", "episodic", "First run")
	if err := Save(c); err != nil {
		t.Fatalf("Save: %v", err)
	}
	if c.ID == "" {
		t.Error("ID should be set after Save")
	}
	if c.Status != "proposed" {
		t.Errorf("default status: want 'proposed', got %q", c.Status)
	}

	got, err := Get(c.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.ID != c.ID {
		t.Errorf("ID mismatch: want %q, got %q", c.ID, got.ID)
	}
	if got.Title != c.Title {
		t.Errorf("Title: want %q, got %q", c.Title, got.Title)
	}
	if got.Content != c.Content {
		t.Errorf("Content: want %q, got %q", c.Content, got.Content)
	}
}

func TestList(t *testing.T) {
	agent := "bob"
	for i, title := range []string{"Memory A", "Memory B", "Memory C"} {
		layer := "episodic"
		if i == 2 {
			layer = "working"
		}
		c := newChunk(agent, layer, title)
		if err := Save(c); err != nil {
			t.Fatalf("Save %q: %v", title, err)
		}
	}

	all, err := List("", agent, "", "")
	if err != nil {
		t.Fatalf("List all: %v", err)
	}
	if len(all) < 3 {
		t.Errorf("want >=3 chunks for bob, got %d", len(all))
	}

	episodic, err := List("episodic", agent, "", "")
	if err != nil {
		t.Fatalf("List episodic: %v", err)
	}
	for _, c := range episodic {
		if c.Layer != "episodic" {
			t.Errorf("layer filter: expected episodic, got %q", c.Layer)
		}
	}
}

func TestSetStatusPromote(t *testing.T) {
	c := newChunk("carol", "semantic_local", "Good finding")
	if err := Save(c); err != nil {
		t.Fatalf("Save: %v", err)
	}

	if err := SetStatus(c.ID, "approved", ""); err != nil {
		t.Fatalf("SetStatus approved: %v", err)
	}

	got, err := Get(c.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.Status != "approved" {
		t.Errorf("want status 'approved', got %q", got.Status)
	}
}

func TestSetStatusReject(t *testing.T) {
	c := newChunk("dave", "episodic", "Bad finding")
	if err := Save(c); err != nil {
		t.Fatalf("Save: %v", err)
	}

	reason := "Not relevant anymore"
	if err := SetStatus(c.ID, "rejected", reason); err != nil {
		t.Fatalf("SetStatus rejected: %v", err)
	}

	got, err := Get(c.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.Status != "rejected" {
		t.Errorf("want status 'rejected', got %q", got.Status)
	}
	if got.RejectionReason != reason {
		t.Errorf("rejection reason: want %q, got %q", reason, got.RejectionReason)
	}
}

func TestListStatusFilter(t *testing.T) {
	agent := "eve"
	proposed := newChunk(agent, "episodic", "Proposed chunk")
	approved := newChunk(agent, "episodic", "Approved chunk")
	if err := Save(proposed); err != nil {
		t.Fatal(err)
	}
	if err := Save(approved); err != nil {
		t.Fatal(err)
	}
	if err := SetStatus(approved.ID, "approved", ""); err != nil {
		t.Fatal(err)
	}

	onlyProposed, err := List("", agent, "", "proposed")
	if err != nil {
		t.Fatalf("List proposed: %v", err)
	}
	for _, c := range onlyProposed {
		if c.Status != "proposed" {
			t.Errorf("status filter: expected proposed, got %q", c.Status)
		}
	}

	onlyApproved, err := List("", agent, "", "approved")
	if err != nil {
		t.Fatalf("List approved: %v", err)
	}
	for _, c := range onlyApproved {
		if c.Status != "approved" {
			t.Errorf("status filter: expected approved, got %q", c.Status)
		}
	}
}

func TestGetNotFound(t *testing.T) {
	_, err := Get("nonexistent-id-xyz")
	if err == nil {
		t.Error("Get nonexistent: expected error, got nil")
	}
}
