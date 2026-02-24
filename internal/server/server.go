package server

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"

	webui "github.com/steveyegge/loguetown/web"

	"github.com/steveyegge/loguetown/internal/agents"
	"github.com/steveyegge/loguetown/internal/chronicle"
	"github.com/steveyegge/loguetown/internal/config"
	"github.com/steveyegge/loguetown/internal/embeddings"
	"github.com/steveyegge/loguetown/internal/memory"
	"github.com/steveyegge/loguetown/internal/plans"
	"github.com/steveyegge/loguetown/internal/roles"
	"github.com/steveyegge/loguetown/internal/skills"
	"github.com/steveyegge/loguetown/internal/storage"
)

// Server handles HTTP requests for the Loguetown GUI.
type Server struct {
	projectPath string
	projectID   string
	mux         *http.ServeMux
}

// New creates and configures the HTTP server for the given project.
func New(projectPath string) (*Server, error) {
	p, err := config.LoadProject(projectPath)
	if err != nil {
		return nil, fmt.Errorf("load project: %w", err)
	}

	s := &Server{
		projectPath: projectPath,
		projectID:   p.Project.ID,
		mux:         http.NewServeMux(),
	}
	s.registerRoutes()
	return s, nil
}

// ServeHTTP implements http.Handler; adds CORS headers for dev mode.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	s.mux.ServeHTTP(w, r)
}

func (s *Server) registerRoutes() {
	// Project
	s.mux.HandleFunc("GET /api/project", s.handleGetProject)

	// Roles
	s.mux.HandleFunc("GET /api/roles", s.handleListRoles)
	s.mux.HandleFunc("GET /api/roles/{name}", s.handleGetRole)
	s.mux.HandleFunc("POST /api/roles", s.handleCreateRole)
	s.mux.HandleFunc("DELETE /api/roles/{name}", s.handleDeleteRole)

	// Agents
	s.mux.HandleFunc("GET /api/agents", s.handleListAgents)
	s.mux.HandleFunc("GET /api/agents/{name}", s.handleGetAgent)
	s.mux.HandleFunc("POST /api/agents", s.handleCreateAgent)
	s.mux.HandleFunc("DELETE /api/agents/{name}", s.handleDeleteAgent)

	// Chronicle
	s.mux.HandleFunc("GET /api/chronicle", s.handleQueryChronicle)

	// Skills
	s.mux.HandleFunc("GET /api/skills", s.handleListSkills)
	s.mux.HandleFunc("POST /api/skills/reindex", s.handleReindexSkills)

	// Memory
	s.mux.HandleFunc("GET /api/memory", s.handleListMemory)
	s.mux.HandleFunc("PATCH /api/memory/{id}", s.handleUpdateMemory)

	// Plans / Tasks / Runs
	s.mux.HandleFunc("GET /api/plans", s.handleListPlans)
	s.mux.HandleFunc("GET /api/plans/{id}", s.handleGetPlan)
	s.mux.HandleFunc("GET /api/tasks", s.handleListTasks)
	s.mux.HandleFunc("GET /api/tasks/{id}", s.handleGetTask)
	s.mux.HandleFunc("GET /api/runs", s.handleListRuns)
	s.mux.HandleFunc("GET /api/runs/{id}", s.handleGetRun)

	// SPA static files (must be last — catch-all)
	sub, _ := fs.Sub(webui.Files, "dist")
	s.mux.Handle("/", spaHandler(sub))
}

// ── Project ──────────────────────────────────────────────────────────────────

func (s *Server) handleGetProject(w http.ResponseWriter, r *http.Request) {
	p, err := config.LoadProject(s.projectPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, p)
}

// ── Roles ─────────────────────────────────────────────────────────────────────

func (s *Server) handleListRoles(w http.ResponseWriter, r *http.Request) {
	names, err := roles.List(s.projectPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}

	var result []*roles.Role
	for _, name := range names {
		role, err := roles.Load(name, s.projectPath)
		if err != nil {
			continue // skip invalid
		}
		result = append(result, role)
	}
	if result == nil {
		result = []*roles.Role{}
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *Server) handleGetRole(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	role, err := roles.Load(name, s.projectPath)
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	writeJSON(w, http.StatusOK, role)
}

func (s *Server) handleCreateRole(w http.ResponseWriter, r *http.Request) {
	var role roles.Role
	if err := json.NewDecoder(r.Body).Decode(&role); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	if err := role.Validate(); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	if roles.Exists(role.Name, s.projectPath) {
		writeError(w, http.StatusConflict, fmt.Errorf("role %q already exists", role.Name))
		return
	}
	if err := roles.Save(&role, s.projectPath); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusCreated, role)
}

func (s *Server) handleDeleteRole(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	if !roles.Exists(name, s.projectPath) {
		writeError(w, http.StatusNotFound, fmt.Errorf("role %q not found", name))
		return
	}
	if err := roles.Delete(name, s.projectPath); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ── Agents ────────────────────────────────────────────────────────────────────

func (s *Server) handleListAgents(w http.ResponseWriter, r *http.Request) {
	names, err := agents.List(s.projectPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}

	var result []*agents.Charter
	for _, name := range names {
		c, err := agents.Load(name, s.projectPath)
		if err != nil {
			continue // skip invalid
		}
		result = append(result, c)
	}
	if result == nil {
		result = []*agents.Charter{}
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *Server) handleGetAgent(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	c, err := agents.Load(name, s.projectPath)
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	writeJSON(w, http.StatusOK, c)
}

func (s *Server) handleCreateAgent(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name  string `json:"name"`
		Role  string `json:"role"`
		Model string `json:"model,omitempty"` // optional model ID override
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	if req.Name == "" || req.Role == "" {
		writeError(w, http.StatusBadRequest, fmt.Errorf("name and role are required"))
		return
	}
	if agents.Exists(req.Name, s.projectPath) {
		writeError(w, http.StatusConflict, fmt.Errorf("agent %q already exists", req.Name))
		return
	}
	c := &agents.Charter{Name: req.Name, Role: req.Role}
	if err := agents.Save(c, s.projectPath); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	loaded, _ := agents.Load(req.Name, s.projectPath)
	writeJSON(w, http.StatusCreated, loaded)
}

func (s *Server) handleDeleteAgent(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	if !agents.Exists(name, s.projectPath) {
		writeError(w, http.StatusNotFound, fmt.Errorf("agent %q not found", name))
		return
	}
	if err := agents.Delete(name, s.projectPath); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ── Chronicle ─────────────────────────────────────────────────────────────────

func (s *Server) handleQueryChronicle(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	filter := chronicle.Filter{
		ProjectID: s.projectID,
		EventType: q.Get("event_type"),
		Actor:     q.Get("actor"),
	}
	if lim := q.Get("limit"); lim != "" {
		if n, err := strconv.Atoi(lim); err == nil {
			filter.Limit = n
		}
	}
	if filter.Limit == 0 {
		filter.Limit = 100
	}

	events, err := chronicle.Query(filter)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	if events == nil {
		events = []chronicle.Event{}
	}
	writeJSON(w, http.StatusOK, events)
}

// ── Skills ────────────────────────────────────────────────────────────────────

// skillRow is the JSON representation of a skill chunk (no embedding bytes).
type skillRow struct {
	ID           string `json:"id"`
	Role         string `json:"role"`
	FilePath     string `json:"file_path"`
	Title        string `json:"title,omitempty"`
	ContentHash  string `json:"content_hash,omitempty"`
	CreatedAt    string `json:"created_at"`
}

func (s *Server) handleListSkills(w http.ResponseWriter, r *http.Request) {
	db, err := storage.Get()
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	rows, err := db.Query(
		`SELECT id, role, file_path, COALESCE(title,''), COALESCE(content_hash,''), created_at
		 FROM skill_files ORDER BY role, file_path, title`,
	)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Errorf("query skill_files: %w", err))
		return
	}
	defer rows.Close()

	result := []skillRow{}
	for rows.Next() {
		var sk skillRow
		if err := rows.Scan(&sk.ID, &sk.Role, &sk.FilePath, &sk.Title, &sk.ContentHash, &sk.CreatedAt); err != nil {
			writeError(w, http.StatusInternalServerError, err)
			return
		}
		result = append(result, sk)
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *Server) handleReindexSkills(w http.ResponseWriter, r *http.Request) {
	cfg, err := config.LoadProject(s.projectPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Errorf("load project config: %w", err))
		return
	}
	provider, err := embeddings.New(cfg.Embeddings)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Errorf("create embedding provider: %w", err))
		return
	}
	skillsDir := filepath.Join(s.projectPath, ".loguetown", "skills")
	result, err := skills.Reindex(skillsDir, "project", "", provider)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{
		"files":   result.Files,
		"chunks":  result.Chunks,
		"skipped": result.Skipped,
	})
}

// ── Memory ────────────────────────────────────────────────────────────────────

func (s *Server) handleListMemory(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	chunks, err := memory.List(q.Get("layer"), q.Get("agent"), s.projectID, q.Get("status"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	if chunks == nil {
		chunks = []memory.Chunk{}
	}
	writeJSON(w, http.StatusOK, chunks)
}

func (s *Server) handleUpdateMemory(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var body struct {
		Status          string `json:"status"`
		RejectionReason string `json:"rejection_reason,omitempty"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	if body.Status != "approved" && body.Status != "rejected" {
		writeError(w, http.StatusBadRequest, fmt.Errorf("status must be 'approved' or 'rejected'"))
		return
	}
	if err := memory.SetStatus(id, body.Status, body.RejectionReason); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	c, err := memory.Get(id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, c)
}

// ── Plans / Tasks / Runs ─────────────────────────────────────────────────────

func (s *Server) handleListPlans(w http.ResponseWriter, r *http.Request) {
	ps, err := plans.ListPlans(s.projectID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	if ps == nil {
		ps = []plans.Plan{}
	}
	writeJSON(w, http.StatusOK, ps)
}

func (s *Server) handleGetPlan(w http.ResponseWriter, r *http.Request) {
	p, err := plans.GetPlan(r.PathValue("id"))
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	writeJSON(w, http.StatusOK, p)
}

func (s *Server) handleListTasks(w http.ResponseWriter, r *http.Request) {
	planID := r.URL.Query().Get("plan_id")
	if planID == "" {
		// Default to most-recent plan.
		ps, err := plans.ListPlans(s.projectID)
		if err != nil || len(ps) == 0 {
			writeJSON(w, http.StatusOK, []plans.Task{})
			return
		}
		planID = ps[0].ID
	}
	ts, err := plans.ListTasks(planID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	if ts == nil {
		ts = []plans.Task{}
	}
	writeJSON(w, http.StatusOK, ts)
}

func (s *Server) handleGetTask(w http.ResponseWriter, r *http.Request) {
	t, err := plans.GetTask(r.PathValue("id"))
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	writeJSON(w, http.StatusOK, t)
}

func (s *Server) handleListRuns(w http.ResponseWriter, r *http.Request) {
	taskID := r.URL.Query().Get("task_id")
	if taskID == "" {
		writeError(w, http.StatusBadRequest, fmt.Errorf("task_id query param required"))
		return
	}
	rs, err := plans.ListRuns(taskID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	if rs == nil {
		rs = []plans.Run{}
	}
	writeJSON(w, http.StatusOK, rs)
}

func (s *Server) handleGetRun(w http.ResponseWriter, r *http.Request) {
	run, err := plans.GetRun(r.PathValue("id"))
	if err != nil {
		writeError(w, http.StatusNotFound, err)
		return
	}
	writeJSON(w, http.StatusOK, run)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, err error) {
	writeJSON(w, status, map[string]string{"error": err.Error()})
}

// spaHandler serves embedded static files with a fallback to index.html for
// React Router paths that don't correspond to real files.
func spaHandler(fsys fs.FS) http.Handler {
	fileServer := http.FileServerFS(fsys)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		name := strings.TrimPrefix(r.URL.Path, "/")
		if name == "" {
			name = "index.html"
		}
		f, err := fsys.Open(name)
		if err != nil {
			// Not a real file — let React Router handle it
			r2 := r.Clone(r.Context())
			r2.URL.Path = "/"
			fileServer.ServeHTTP(w, r2)
			return
		}
		f.Close()
		fileServer.ServeHTTP(w, r)
	})
}
