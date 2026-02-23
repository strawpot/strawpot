package skills

import (
	"os"
	"path/filepath"
	"testing"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "skills-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

// ── chunkByH2 ─────────────────────────────────────────────────────────────────

func TestChunkByH2NoHeadings(t *testing.T) {
	chunks := chunkByH2("Hello world\nThis is a test")
	if len(chunks) != 1 {
		t.Fatalf("want 1 chunk, got %d", len(chunks))
	}
	if chunks[0].heading != "" {
		t.Errorf("want empty heading, got %q", chunks[0].heading)
	}
	if chunks[0].body == "" {
		t.Error("want non-empty body")
	}
}

func TestChunkByH2SingleHeading(t *testing.T) {
	md := "## My Section\nSome content here\nMore lines"
	chunks := chunkByH2(md)
	if len(chunks) != 1 {
		t.Fatalf("want 1 chunk, got %d", len(chunks))
	}
	if chunks[0].heading != "My Section" {
		t.Errorf("want heading %q, got %q", "My Section", chunks[0].heading)
	}
	if chunks[0].body == "" {
		t.Error("want non-empty body")
	}
}

func TestChunkByH2MultipleHeadings(t *testing.T) {
	md := "## Alpha\nContent A\n## Beta\nContent B\n## Gamma\nContent C"
	chunks := chunkByH2(md)
	if len(chunks) != 3 {
		t.Fatalf("want 3 chunks, got %d", len(chunks))
	}
	headings := []string{"Alpha", "Beta", "Gamma"}
	for i, want := range headings {
		if chunks[i].heading != want {
			t.Errorf("[%d] want heading %q, got %q", i, want, chunks[i].heading)
		}
	}
}

func TestChunkByH2PreamblesSkipped(t *testing.T) {
	// Text before the first ## should be ignored.
	md := "# Title\nsome intro\n## Section\nBody here"
	chunks := chunkByH2(md)
	// Only the H2 section should be present.
	if len(chunks) != 1 {
		t.Fatalf("want 1 chunk (preamble skipped), got %d", len(chunks))
	}
	if chunks[0].heading != "Section" {
		t.Errorf("want heading %q, got %q", "Section", chunks[0].heading)
	}
}

func TestChunkByH2EmptyContent(t *testing.T) {
	chunks := chunkByH2("")
	if len(chunks) != 1 {
		t.Fatalf("want 1 fallback chunk, got %d", len(chunks))
	}
}

// ── Reindex ───────────────────────────────────────────────────────────────────

// mockProvider returns a constant deterministic embedding.
type mockProvider struct{ dims int }

func (m *mockProvider) Embed(_ string) ([]float32, error) {
	v := make([]float32, m.dims)
	for i := range v {
		v[i] = float32(i+1) / float32(m.dims)
	}
	return v, nil
}
func (m *mockProvider) Dimensions() int { return m.dims }

func TestReindexCreatesChunks(t *testing.T) {
	skillsDir := t.TempDir()

	// Write a skill file with two H2 sections.
	content := "## Tip One\nDo this.\n## Tip Two\nDo that.\n"
	path := filepath.Join(skillsDir, "myskill.md")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	result, err := Reindex(skillsDir, &mockProvider{dims: 4})
	if err != nil {
		t.Fatalf("Reindex: %v", err)
	}
	if result.Files != 1 {
		t.Errorf("want 1 file, got %d", result.Files)
	}
	if result.Chunks != 2 {
		t.Errorf("want 2 chunks, got %d", result.Chunks)
	}
	if result.Skipped != 0 {
		t.Errorf("want 0 skipped, got %d", result.Skipped)
	}
}

func TestReindexSkipsUnchanged(t *testing.T) {
	skillsDir := t.TempDir()

	content := "## Section\nBody\n"
	path := filepath.Join(skillsDir, "stable.md")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	provider := &mockProvider{dims: 4}

	// First index.
	r1, err := Reindex(skillsDir, provider)
	if err != nil {
		t.Fatalf("first Reindex: %v", err)
	}
	if r1.Chunks != 1 {
		t.Fatalf("first Reindex: want 1 chunk, got %d", r1.Chunks)
	}

	// Second index — same file content should be skipped.
	r2, err := Reindex(skillsDir, provider)
	if err != nil {
		t.Fatalf("second Reindex: %v", err)
	}
	if r2.Skipped != 1 {
		t.Errorf("second Reindex: want 1 skipped, got %d", r2.Skipped)
	}
	if r2.Chunks != 0 {
		t.Errorf("second Reindex: want 0 new chunks, got %d", r2.Chunks)
	}
}

func TestReindexReindexesOnChange(t *testing.T) {
	skillsDir := t.TempDir()

	path := filepath.Join(skillsDir, "changing.md")
	write := func(content string) {
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	provider := &mockProvider{dims: 4}

	write("## V1\nFirst version\n")
	r1, err := Reindex(skillsDir, provider)
	if err != nil || r1.Chunks != 1 {
		t.Fatalf("v1: err=%v chunks=%d", err, r1.Chunks)
	}

	write("## V2a\nSecond version\n## V2b\nAlso added\n")
	r2, err := Reindex(skillsDir, provider)
	if err != nil {
		t.Fatalf("v2 Reindex: %v", err)
	}
	if r2.Chunks != 2 {
		t.Errorf("v2: want 2 chunks, got %d", r2.Chunks)
	}
	if r2.Skipped != 0 {
		t.Errorf("v2: want 0 skipped, got %d", r2.Skipped)
	}
}

func TestReindexIgnoresNonMarkdown(t *testing.T) {
	skillsDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(skillsDir, "notes.txt"), []byte("ignore me"), 0o644); err != nil {
		t.Fatal(err)
	}
	result, err := Reindex(skillsDir, &mockProvider{dims: 4})
	if err != nil {
		t.Fatalf("Reindex: %v", err)
	}
	if result.Files != 0 {
		t.Errorf("want 0 .md files, got %d", result.Files)
	}
}
