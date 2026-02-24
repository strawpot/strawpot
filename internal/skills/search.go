package skills

import (
	"fmt"

	"github.com/steveyegge/loguetown/internal/embeddings"
	"github.com/steveyegge/loguetown/internal/storage"
)

// Result is a skill chunk with its similarity score.
type Result struct {
	ID        string
	Role      string
	FilePath  string
	Title     string
	Content   string // raw chunk body text
	Scope     string // "global", "project", or "agent"
	AgentName string // non-empty only for agent-scoped skills
	Score     float32
}

// Search embeds query, loads all indexed skill chunks from the DB, and
// returns up to topK results with score >= minSim in descending order.
// Results from all scopes (global and project) are searched together.
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
		`SELECT id, role, file_path, COALESCE(title,''), COALESCE(content,''),
		        COALESCE(scope,'project'), COALESCE(agent_name,''), embedding
		 FROM skill_files WHERE embedding IS NOT NULL`,
	)
	if err != nil {
		return nil, fmt.Errorf("query skill_files: %w", err)
	}
	defer rows.Close()

	var items []embeddings.EmbedItem
	type meta struct{ id, role, filePath, title, content, scope, agentName string }
	var metas []meta

	for rows.Next() {
		var id, role, filePath, title, content, scope, agentName string
		var blob []byte
		if err := rows.Scan(&id, &role, &filePath, &title, &content, &scope, &agentName, &blob); err != nil {
			return nil, fmt.Errorf("scan skill_files: %w", err)
		}
		vec := embeddings.BytesToFloat32s(blob)
		if len(vec) == 0 {
			continue
		}
		items = append(items, embeddings.EmbedItem{ID: id, Embedding: vec})
		metas = append(metas, meta{id: id, role: role, filePath: filePath, title: title, content: content, scope: scope, agentName: agentName})
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
			ID:        s.ID,
			Role:      m.role,
			FilePath:  m.filePath,
			Title:     m.title,
			Content:   m.content,
			Scope:     m.scope,
			AgentName: m.agentName,
			Score:     s.Score,
		})
	}
	return results, nil
}
