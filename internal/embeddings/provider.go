// Package embeddings provides a pluggable interface for generating text embeddings.
package embeddings

// Provider generates dense vector embeddings from text.
type Provider interface {
	// Embed returns the embedding vector for the given text.
	Embed(text string) ([]float32, error)
	// Dimensions returns the fixed vector length this provider produces.
	Dimensions() int
}

// EmbedItem pairs a text chunk with its pre-computed embedding, used for
// similarity search.
type EmbedItem struct {
	ID        string
	Text      string
	Embedding []float32
	// Metadata — callers may store arbitrary context here.
	Meta map[string]string
}
