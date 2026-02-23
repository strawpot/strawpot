package embeddings

import (
	"encoding/binary"
	"math"
)

// CosineSim returns the cosine similarity between two equal-length vectors.
// Returns 0 if either vector is zero-length or all zeros.
func CosineSim(a, b []float32) float32 {
	if len(a) != len(b) || len(a) == 0 {
		return 0
	}
	var dot, normA, normB float64
	for i := range a {
		dot += float64(a[i]) * float64(b[i])
		normA += float64(a[i]) * float64(a[i])
		normB += float64(b[i]) * float64(b[i])
	}
	denom := math.Sqrt(normA) * math.Sqrt(normB)
	if denom == 0 {
		return 0
	}
	return float32(dot / denom)
}

// ScoredItem is an EmbedItem with its similarity score.
type ScoredItem struct {
	EmbedItem
	Score float32
}

// TopK returns up to k items from items sorted by descending cosine similarity
// to query. Items with no embedding or score below minSim are excluded.
func TopK(query []float32, items []EmbedItem, k int, minSim float32) []ScoredItem {
	var scored []ScoredItem
	for _, item := range items {
		if len(item.Embedding) == 0 {
			continue
		}
		score := CosineSim(query, item.Embedding)
		if score >= minSim {
			scored = append(scored, ScoredItem{EmbedItem: item, Score: score})
		}
	}
	// Sort descending by score (insertion sort — typically small N)
	for i := 1; i < len(scored); i++ {
		for j := i; j > 0 && scored[j].Score > scored[j-1].Score; j-- {
			scored[j], scored[j-1] = scored[j-1], scored[j]
		}
	}
	if k > 0 && len(scored) > k {
		scored = scored[:k]
	}
	return scored
}

// Float32sToBytes serialises a float32 slice as little-endian bytes for SQLite BLOB storage.
func Float32sToBytes(fs []float32) []byte {
	buf := make([]byte, len(fs)*4)
	for i, f := range fs {
		binary.LittleEndian.PutUint32(buf[i*4:], math.Float32bits(f))
	}
	return buf
}

// BytesToFloat32s deserialises a BLOB back to a float32 slice.
func BytesToFloat32s(b []byte) []float32 {
	if len(b)%4 != 0 {
		return nil
	}
	fs := make([]float32, len(b)/4)
	for i := range fs {
		bits := binary.LittleEndian.Uint32(b[i*4:])
		fs[i] = math.Float32frombits(bits)
	}
	return fs
}
