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

// ── Retrieve tests ─────────────────────────────────────────────────────────────

// mockEmbedProvider returns a constant deterministic embedding for retrieval tests.
type mockEmbedProvider struct{}

func (m *mockEmbedProvider) Embed(_ string) ([]float32, error) {
	return []float32{1.0, 0.0, 0.0, 0.0}, nil
}
func (m *mockEmbedProvider) Dimensions() int { return 4 }

// saveApproved saves a chunk and immediately promotes it to "approved".
func saveApproved(t *testing.T, c *Chunk) *Chunk {
	t.Helper()
	if err := Save(c); err != nil {
		t.Fatalf("Save: %v", err)
	}
	if err := SetStatus(c.ID, "approved", ""); err != nil {
		t.Fatalf("SetStatus approved: %v", err)
	}
	return c
}

func TestRetrieveNilProvider(t *testing.T) {
	c := saveApproved(t, &Chunk{
		AgentName: "ret-nil-agent",
		Layer:     "episodic",
		ProjectID: "proj-ret-nil",
		FilePath:  "ret-nil.md",
		Title:     "Retrieve nil provider test",
		Content:   "Some content",
	})

	results, err := Retrieve("episodic", "proj-ret-nil", "ret-nil-agent", "", 10, 0, nil)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	found := false
	for _, r := range results {
		if r.ID == c.ID {
			found = true
		}
	}
	if !found {
		t.Errorf("expected to find approved chunk %q in nil-provider results", c.ID)
	}
}

func TestRetrieveOnlyApproved(t *testing.T) {
	pid := "proj-only-approved"
	agent := "only-approved-agent"

	proposed := newChunk(agent, "episodic", "Proposed - should not appear")
	proposed.ProjectID = pid
	if err := Save(proposed); err != nil {
		t.Fatalf("Save proposed: %v", err)
	}

	approved := saveApproved(t, &Chunk{
		AgentName: agent,
		Layer:     "episodic",
		ProjectID: pid,
		FilePath:  "approved.md",
		Title:     "Approved - should appear",
		Content:   "Content",
	})

	results, err := Retrieve("episodic", pid, agent, "", 10, 0, nil)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	for _, r := range results {
		if r.Status != "approved" {
			t.Errorf("Retrieve returned non-approved chunk %q (status=%q)", r.Title, r.Status)
		}
	}
	found := false
	for _, r := range results {
		if r.ID == approved.ID {
			found = true
		}
	}
	if !found {
		t.Error("expected to find the approved chunk in results")
	}
}

func TestRetrieveAgentFilter(t *testing.T) {
	pid := "proj-agent-filter"
	agent1 := "agent-filter-1"
	agent2 := "agent-filter-2"

	c1 := saveApproved(t, &Chunk{AgentName: agent1, Layer: "episodic", ProjectID: pid, FilePath: "c1.md", Title: "Agent1 chunk", Content: "content1"})
	saveApproved(t, &Chunk{AgentName: agent2, Layer: "episodic", ProjectID: pid, FilePath: "c2.md", Title: "Agent2 chunk", Content: "content2"})

	results, err := Retrieve("episodic", pid, agent1, "", 10, 0, nil)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	for _, r := range results {
		if r.AgentName != agent1 {
			t.Errorf("agentName filter: unexpected agent_name %q", r.AgentName)
		}
	}
	found := false
	for _, r := range results {
		if r.ID == c1.ID {
			found = true
		}
	}
	if !found {
		t.Error("expected agent1's chunk in filtered results")
	}
}

func TestRetrieveProjectFilter(t *testing.T) {
	agent := "proj-filter-agent"

	cA := saveApproved(t, &Chunk{AgentName: agent, Layer: "semantic_local", ProjectID: "proj-filter-A", FilePath: "a.md", Title: "Project A chunk", Content: "content A"})
	saveApproved(t, &Chunk{AgentName: agent, Layer: "semantic_local", ProjectID: "proj-filter-B", FilePath: "b.md", Title: "Project B chunk", Content: "content B"})

	results, err := Retrieve("semantic_local", "proj-filter-A", "", "", 10, 0, nil)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	for _, r := range results {
		if r.ProjectID != "proj-filter-A" {
			t.Errorf("projectID filter: unexpected project_id %q", r.ProjectID)
		}
	}
	found := false
	for _, r := range results {
		if r.ID == cA.ID {
			found = true
		}
	}
	if !found {
		t.Error("expected proj-A chunk in filtered results")
	}
}
