package skills

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/steveyegge/loguetown/internal/embeddings"
	"github.com/steveyegge/loguetown/internal/storage"
)

// IndexResult summarises a reindex run.
type IndexResult struct {
	Files   int
	Chunks  int
	Skipped int
}

// Reindex walks skillsDir (.loguetown/skills/), chunks each .md file by H2
// heading, embeds each chunk, and upserts the results into skill_files.
func Reindex(skillsDir string, provider embeddings.Provider) (IndexResult, error) {
	db, err := storage.Get()
	if err != nil {
		return IndexResult{}, err
	}

	var result IndexResult

	err = filepath.WalkDir(skillsDir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, ".md") {
			return nil
		}

		result.Files++

		data, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read %s: %w", path, err)
		}

		hash := fmt.Sprintf("%x", sha256.Sum256(data))

		// Relative path for storage (e.g. "implementer/typescript-patterns.md")
		relPath, _ := filepath.Rel(skillsDir, path)
		relPath = filepath.ToSlash(relPath)

		// Skip if content hash is unchanged.
		var existing string
		_ = db.QueryRow(
			"SELECT content_hash FROM skill_files WHERE file_path = ? LIMIT 1",
			relPath,
		).Scan(&existing)
		if existing == hash {
			result.Skipped++
			return nil
		}

		// Role = parent directory name; top-level files use "shared".
		role := filepath.Base(filepath.Dir(relPath))
		if role == "." {
			role = "shared"
		}

		chunks := chunkByH2(string(data))

		// Remove stale rows for this file before reinserting.
		if _, err := db.Exec("DELETE FROM skill_files WHERE file_path = ?", relPath); err != nil {
			return fmt.Errorf("delete old skill rows for %s: %w", relPath, err)
		}

		now := time.Now().UTC().Format(time.RFC3339)
		for _, c := range chunks {
			text := c.heading + "\n\n" + c.body
			vec, err := provider.Embed(text)
			if err != nil {
				return fmt.Errorf("embed %s / %q: %w", relPath, c.heading, err)
			}
			blob := embeddings.Float32sToBytes(vec)

			if _, err := db.Exec(
				`INSERT INTO skill_files (id, role, file_path, title, embedding, content_hash, created_at)
				 VALUES (?, ?, ?, ?, ?, ?, ?)`,
				uuid.New().String(), role, relPath, c.heading, blob, hash, now,
			); err != nil {
				return fmt.Errorf("insert skill chunk: %w", err)
			}
			result.Chunks++
		}
		return nil
	})

	return result, err
}

type mdChunk struct {
	heading string
	body    string
}

// chunkByH2 splits markdown content on "## " headings.
// The whole file is one chunk if there are no H2 headings.
func chunkByH2(content string) []mdChunk {
	var chunks []mdChunk
	var cur *mdChunk

	for _, line := range strings.Split(content, "\n") {
		if strings.HasPrefix(line, "## ") {
			if cur != nil {
				cur.body = strings.TrimSpace(cur.body)
				chunks = append(chunks, *cur)
			}
			cur = &mdChunk{heading: strings.TrimPrefix(line, "## ")}
		} else if cur != nil {
			cur.body += line + "\n"
		}
		// Preamble before first H2 is silently skipped.
	}

	if cur != nil {
		cur.body = strings.TrimSpace(cur.body)
		chunks = append(chunks, *cur)
	}
	if len(chunks) == 0 {
		chunks = []mdChunk{{heading: "", body: strings.TrimSpace(content)}}
	}
	return chunks
}
