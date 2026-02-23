package embeddings

import (
	"math"
	"testing"
)

// ── CosineSim ─────────────────────────────────────────────────────────────────

func TestCosineSimIdentical(t *testing.T) {
	v := []float32{1, 2, 3}
	got := CosineSim(v, v)
	if math.Abs(float64(got)-1.0) > 1e-6 {
		t.Errorf("identical vectors: want ~1.0, got %v", got)
	}
}

func TestCosineSimOrthogonal(t *testing.T) {
	a := []float32{1, 0}
	b := []float32{0, 1}
	got := CosineSim(a, b)
	if math.Abs(float64(got)) > 1e-6 {
		t.Errorf("orthogonal vectors: want ~0, got %v", got)
	}
}

func TestCosineSimOpposite(t *testing.T) {
	a := []float32{1, 0}
	b := []float32{-1, 0}
	got := CosineSim(a, b)
	if math.Abs(float64(got)+1.0) > 1e-6 {
		t.Errorf("opposite vectors: want ~-1.0, got %v", got)
	}
}

func TestCosineSimZeroVector(t *testing.T) {
	z := []float32{0, 0, 0}
	v := []float32{1, 2, 3}
	if CosineSim(z, v) != 0 {
		t.Error("zero vector: want 0")
	}
	if CosineSim(v, z) != 0 {
		t.Error("zero vector (reversed): want 0")
	}
}

func TestCosineSimLengthMismatch(t *testing.T) {
	if CosineSim([]float32{1, 2}, []float32{1}) != 0 {
		t.Error("length mismatch: want 0")
	}
}

func TestCosineSimEmpty(t *testing.T) {
	if CosineSim([]float32{}, []float32{}) != 0 {
		t.Error("empty: want 0")
	}
}

// ── TopK ──────────────────────────────────────────────────────────────────────

func TestTopKOrdering(t *testing.T) {
	// Two items: one close to query (1,0), one far (0,1).
	query := []float32{1, 0}
	items := []EmbedItem{
		{ID: "far", Embedding: []float32{0, 1}},
		{ID: "close", Embedding: []float32{1, 0}},
	}
	got := TopK(query, items, 2, -1)
	if len(got) != 2 {
		t.Fatalf("want 2 results, got %d", len(got))
	}
	if got[0].ID != "close" {
		t.Errorf("first result should be 'close', got %q", got[0].ID)
	}
}

func TestTopKLimit(t *testing.T) {
	query := []float32{1, 0}
	items := []EmbedItem{
		{ID: "a", Embedding: []float32{1, 0}},
		{ID: "b", Embedding: []float32{1, 0}},
		{ID: "c", Embedding: []float32{1, 0}},
	}
	got := TopK(query, items, 2, -1)
	if len(got) != 2 {
		t.Errorf("TopK(k=2): want 2, got %d", len(got))
	}
}

func TestTopKMinSim(t *testing.T) {
	query := []float32{1, 0}
	items := []EmbedItem{
		{ID: "match", Embedding: []float32{1, 0}},   // sim ~1.0
		{ID: "no", Embedding: []float32{0, 1}},       // sim ~0.0
	}
	got := TopK(query, items, 10, 0.5)
	if len(got) != 1 || got[0].ID != "match" {
		t.Errorf("minSim=0.5: want only 'match', got %v", got)
	}
}

func TestTopKSkipsEmptyEmbedding(t *testing.T) {
	query := []float32{1, 0}
	items := []EmbedItem{
		{ID: "empty"},
		{ID: "ok", Embedding: []float32{1, 0}},
	}
	got := TopK(query, items, 10, -1)
	if len(got) != 1 || got[0].ID != "ok" {
		t.Errorf("want only 'ok' (empty embedding skipped), got %v", got)
	}
}

func TestTopKKZeroReturnsAll(t *testing.T) {
	query := []float32{1, 0}
	items := []EmbedItem{
		{ID: "a", Embedding: []float32{1, 0}},
		{ID: "b", Embedding: []float32{1, 0}},
	}
	got := TopK(query, items, 0, -1) // k=0 means no cap
	if len(got) != 2 {
		t.Errorf("k=0 (no cap): want 2, got %d", len(got))
	}
}

// ── Float32 serialisation ──────────────────────────────────────────────────────

func TestFloat32sRoundtrip(t *testing.T) {
	orig := []float32{0.1, -0.5, 3.14159, 0, 1e-10, 1e10}
	got := BytesToFloat32s(Float32sToBytes(orig))
	if len(got) != len(orig) {
		t.Fatalf("length mismatch: want %d, got %d", len(orig), len(got))
	}
	for i := range orig {
		if got[i] != orig[i] {
			t.Errorf("[%d] want %v, got %v", i, orig[i], got[i])
		}
	}
}

func TestBytesToFloat32sOddLength(t *testing.T) {
	if BytesToFloat32s([]byte{1, 2, 3}) != nil {
		t.Error("odd byte slice: want nil")
	}
}

func TestBytesToFloat32sEmpty(t *testing.T) {
	if got := BytesToFloat32s([]byte{}); len(got) != 0 {
		t.Errorf("empty: want empty slice, got %v", got)
	}
}
