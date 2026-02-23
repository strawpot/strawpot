package skills

import (
	"fmt"

	"github.com/steveyegge/loguetown/internal/embeddings"
	"github.com/steveyegge/loguetown/internal/storage"
)

// Result is a skill chunk with its similarity score.
type Result struct {
	ID       string
	Role     string
	FilePath string
	Title    string
	Score    float32
}

// Search embeds query, loads all indexed skill chunks from the DB, and
// returns up to topK results with score >= minSim in descending order.
func Search(query string, provider embeddings.Provider, topK int, minSim float32) ([]Result, error) {
	queryVec, err := provider.Embed(query)
	if err != nil {
		return nil, fmt.Errorf("embed query: %w", err)
	}

	db, err := storage.Get()
	if err != nil {
		return nil, err
	}

	rows, err := db.Query(
		"SELECT id, role, file_path, title, embedding FROM skill_files WHERE embedding IS NOT NULL",
	)
	if err != nil {
		return nil, fmt.Errorf("query skill_files: %w", err)
	}
	defer rows.Close()

	var items []embeddings.EmbedItem
	type meta struct{ id, role, filePath, title string }
	var metas []meta

	for rows.Next() {
		var id, role, filePath string
		var title *string
		var blob []byte
		if err := rows.Scan(&id, &role, &filePath, &title, &blob); err != nil {
			return nil, fmt.Errorf("scan skill_files: %w", err)
		}
		vec := embeddings.BytesToFloat32s(blob)
		if len(vec) == 0 {
			continue
		}
		t := ""
		if title != nil {
			t = *title
		}
		items = append(items, embeddings.EmbedItem{ID: id, Embedding: vec})
		metas = append(metas, meta{id: id, role: role, filePath: filePath, title: t})
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rows err: %w", err)
	}

	scored := embeddings.TopK(queryVec, items, topK, minSim)

	// Re-attach metadata using a lookup map.
	metaMap := make(map[string]meta, len(metas))
	for _, m := range metas {
		metaMap[m.id] = m
	}

	results := make([]Result, 0, len(scored))
	for _, s := range scored {
		m := metaMap[s.ID]
		results = append(results, Result{
			ID:       s.ID,
			Role:     m.role,
			FilePath: m.filePath,
			Title:    m.title,
			Score:    s.Score,
		})
	}
	return results, nil
}
