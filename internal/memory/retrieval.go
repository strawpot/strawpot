package memory

import (
	"fmt"

	"github.com/steveyegge/loguetown/internal/embeddings"
	"github.com/steveyegge/loguetown/internal/storage"
)

// RetrieveResult is a memory chunk with its similarity score.
type RetrieveResult struct {
	Chunk
	Score float32
}

// Retrieve returns the top-K approved memory chunks for a given layer/project
// that are semantically similar to query. Returns chunks ordered by descending
// score. If provider is nil, returns approved chunks in insertion order.
func Retrieve(layer, projectID, query string, topK int, minSim float32, provider embeddings.Provider) ([]RetrieveResult, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}

	q := `SELECT id, agent_name, layer, COALESCE(project_id,''),
	             file_path, COALESCE(title,''), COALESCE(content,''),
	             status, COALESCE(rejection_reason,''), created_at,
	             embedding
	      FROM memory_chunks
	      WHERE status = 'approved'`
	var args []interface{}

	if layer != "" {
		q += " AND layer = ?"
		args = append(args, layer)
	}
	if projectID != "" {
		q += " AND project_id = ?"
		args = append(args, projectID)
	}

	rows, err := db.Query(q, args...)
	if err != nil {
		return nil, fmt.Errorf("retrieve memory_chunks: %w", err)
	}
	defer rows.Close()

	type row struct {
		Chunk
		blob []byte
	}
	var candidates []row

	for rows.Next() {
		var r row
		var blob []byte
		if err := rows.Scan(
			&r.ID, &r.AgentName, &r.Layer, &r.ProjectID,
			&r.FilePath, &r.Title, &r.Content,
			&r.Status, &r.RejectionReason, &r.CreatedAt,
			&blob,
		); err != nil {
			return nil, fmt.Errorf("scan memory chunk: %w", err)
		}
		r.blob = blob
		candidates = append(candidates, r)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// No provider — return top-K by insertion order without scoring.
	if provider == nil || query == "" {
		n := len(candidates)
		if topK > 0 && n > topK {
			n = topK
		}
		results := make([]RetrieveResult, n)
		for i, c := range candidates[:n] {
			results[i] = RetrieveResult{Chunk: c.Chunk}
		}
		return results, nil
	}

	// Embed query and run cosine similarity.
	queryVec, err := provider.Embed(query)
	if err != nil {
		return nil, fmt.Errorf("embed retrieval query: %w", err)
	}

	items := make([]embeddings.EmbedItem, 0, len(candidates))
	for _, c := range candidates {
		if len(c.blob) == 0 {
			continue
		}
		items = append(items, embeddings.EmbedItem{
			ID:        c.ID,
			Embedding: embeddings.BytesToFloat32s(c.blob),
		})
	}

	scored := embeddings.TopK(queryVec, items, topK, minSim)

	// Build ID → Chunk map.
	chunkMap := make(map[string]Chunk, len(candidates))
	for _, c := range candidates {
		chunkMap[c.ID] = c.Chunk
	}

	results := make([]RetrieveResult, 0, len(scored))
	for _, s := range scored {
		results = append(results, RetrieveResult{
			Chunk: chunkMap[s.ID],
			Score: s.Score,
		})
	}
	return results, nil
}
