"""Tests for conversation endpoints."""

import uuid
from unittest.mock import patch

from test_sessions_sync import _register_project

from strawpot_gui.db import get_db
from strawpot_gui.routers.conversations import _build_conversation_context


def _create_conversation(client, project_id, title=None):
    body = {"project_id": project_id}
    if title:
        body["title"] = title
    resp = client.post("/api/conversations", json=body)
    assert resp.status_code == 201
    return resp.json()


def _submit_task(client, conversation_id, task="Do something", **kwargs):
    """Submit a task using a mocked subprocess."""
    body = {"task": task, **kwargs}
    with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
         patch("strawpot_gui.routers.sessions.subprocess.Popen"), \
         patch("strawpot_gui.routers.sessions.load_config") as mock_config:
        from strawpot.config import StrawPotConfig
        mock_config.return_value = StrawPotConfig()
        return client.post(f"/api/conversations/{conversation_id}/tasks", json=body)


class TestCreateConversation:
    def test_returns_201(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        resp = client.post("/api/conversations", json={"project_id": pid})
        assert resp.status_code == 201

    def test_response_shape(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        data = _create_conversation(client, pid, title="My Chat")
        assert data["project_id"] == pid
        assert data["title"] == "My Chat"
        assert "id" in data
        assert "created_at" in data

    def test_title_defaults_to_null(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        data = _create_conversation(client, pid)
        assert data["title"] is None

    def test_unknown_project_returns_404(self, client):
        resp = client.post("/api/conversations", json={"project_id": 9999})
        assert resp.status_code == 404


class TestGetConversation:
    def test_get_existing(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = client.get(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == conv["id"]
        assert data["project_id"] == pid
        assert "sessions" in data
        assert "has_more" in data

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/conversations/9999")
        assert resp.status_code == 404

    def test_empty_sessions_list(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        data = client.get(f"/api/conversations/{conv['id']}").json()
        assert data["sessions"] == []
        assert data["has_more"] is False

    def test_sessions_after_task_submission(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        _submit_task(client, conv["id"], task="Build it")
        data = client.get(f"/api/conversations/{conv['id']}").json()
        assert len(data["sessions"]) == 1

    def test_pagination_limit(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        for _ in range(3):
            _submit_task(client, conv["id"])
        data = client.get(f"/api/conversations/{conv['id']}?limit=2").json()
        assert len(data["sessions"]) == 2
        assert data["has_more"] is True

    def test_pagination_no_more(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        _submit_task(client, conv["id"])
        data = client.get(f"/api/conversations/{conv['id']}?limit=20").json()
        assert len(data["sessions"]) == 1
        assert data["has_more"] is False


class TestListProjectConversations:
    def test_empty_list(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        resp = client.get(f"/api/projects/{pid}/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_lists_conversations(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        _create_conversation(client, pid, title="First")
        _create_conversation(client, pid, title="Second")
        data = client.get(f"/api/projects/{pid}/conversations").json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_unknown_project_returns_404(self, client):
        resp = client.get("/api/projects/9999/conversations")
        assert resp.status_code == 404

    def test_scoped_to_project(self, client, tmp_path):
        d1 = tmp_path / "p1"
        d1.mkdir()
        d2 = tmp_path / "p2"
        d2.mkdir()
        pid1 = _register_project(client, d1)
        pid2 = _register_project(client, d2)
        _create_conversation(client, pid1)
        _create_conversation(client, pid2)
        _create_conversation(client, pid2)
        assert client.get(f"/api/projects/{pid1}/conversations").json()["total"] == 1
        assert client.get(f"/api/projects/{pid2}/conversations").json()["total"] == 2

    def test_pagination(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        for _ in range(5):
            _create_conversation(client, pid)
        data = client.get(f"/api/projects/{pid}/conversations?per_page=3&page=1").json()
        assert len(data["items"]) == 3
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["per_page"] == 3


class TestListRecentConversations:
    def test_empty(self, client):
        resp = client.get("/api/conversations/recent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_across_projects(self, client, tmp_path):
        d1 = tmp_path / "p1"
        d1.mkdir()
        d2 = tmp_path / "p2"
        d2.mkdir()
        pid1 = _register_project(client, d1)
        pid2 = _register_project(client, d2)
        _create_conversation(client, pid1)
        _create_conversation(client, pid2)
        items = client.get("/api/conversations/recent").json()
        assert len(items) == 2

    def test_limit_param(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        for _ in range(5):
            _create_conversation(client, pid)
        items = client.get("/api/conversations/recent?limit=3").json()
        assert len(items) == 3

    def test_includes_project_name(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        _create_conversation(client, pid)
        items = client.get("/api/conversations/recent").json()
        assert "project_name" in items[0]


class TestSubmitTask:
    def test_returns_201_with_run_id(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = _submit_task(client, conv["id"], task="Write tests")
        assert resp.status_code == 201
        data = resp.json()
        assert data["run_id"].startswith("run_")
        assert data["conversation_id"] == conv["id"]

    def test_auto_sets_title_from_first_message(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        assert conv["title"] is None
        _submit_task(client, conv["id"], task="Implement the login page")
        updated = client.get(f"/api/conversations/{conv['id']}").json()
        assert updated["title"] == "Implement the login page"

    def test_does_not_overwrite_existing_title(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid, title="Fixed Title")
        _submit_task(client, conv["id"], task="Some task")
        updated = client.get(f"/api/conversations/{conv['id']}").json()
        assert updated["title"] == "Fixed Title"

    def test_unknown_conversation_returns_404(self, client):
        resp = _submit_task(client, 9999)
        assert resp.status_code == 404

    def test_session_linked_to_conversation(self, client, tmp_path, app):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = _submit_task(client, conv["id"], task="Do work")
        run_id = resp.json()["run_id"]
        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT conversation_id FROM sessions WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row["conversation_id"] == conv["id"]

    def test_context_prepended_on_second_turn(self, client, tmp_path, app):
        """Second task should have prior conversation context in the full task."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp1 = _submit_task(client, conv["id"], task="First task")
        run_id1 = resp1.json()["run_id"]
        # Mark first session as completed so it appears in context
        with get_db(app.state.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET status = 'completed', summary = 'did first task' "
                "WHERE run_id = ?", (run_id1,),
            )
        resp2 = _submit_task(client, conv["id"], task="Second task")
        run_id2 = resp2.json()["run_id"]
        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT task, user_task FROM sessions WHERE run_id = ?", (run_id2,)
            ).fetchone()
        # user_task is the raw message; task has context prepended
        assert row["user_task"] == "Second task"
        assert "Prior Conversation" in row["task"]
        assert "Second task" in row["task"]


class TestUpdateConversation:
    def test_update_title(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = client.patch(f"/api/conversations/{conv['id']}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_update_missing_returns_404(self, client):
        resp = client.patch("/api/conversations/9999", json={"title": "X"})
        assert resp.status_code == 404


class TestDeleteConversation:
    def test_delete_removes_conversation(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = client.delete(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 204
        resp = client.get(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 404

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/api/conversations/9999")
        assert resp.status_code == 404

    def test_delete_unlinks_sessions(self, client, tmp_path, app):
        """Sessions belonging to the conversation lose their conversation_id FK."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = _submit_task(client, conv["id"])
        run_id = resp.json()["run_id"]

        client.delete(f"/api/conversations/{conv['id']}")

        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT conversation_id FROM sessions WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row["conversation_id"] is None


# ---------------------------------------------------------------------------
# _build_conversation_context unit tests
# ---------------------------------------------------------------------------


def _insert_completed_session(
    conn, project_id, conversation_id, *,
    task="do something", user_task=None, summary="done", exit_code=0,
    status="completed", started_at=None, files_changed=None,
):
    """Insert a session row directly for testing context building."""
    run_id = uuid.uuid4().hex[:12]
    if started_at is None:
        started_at = "2026-01-01T00:00:00"
    import json as _json
    fc_json = _json.dumps(files_changed) if files_changed else None
    conn.execute(
        "INSERT INTO sessions "
        "(run_id, project_id, role, runtime, isolation, status, task, user_task, "
        "summary, exit_code, conversation_id, started_at, session_dir, "
        "files_changed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, project_id, "default", "claude-code", "none", status, task,
         user_task, summary, exit_code, conversation_id, started_at,
         f"/tmp/{run_id}", fc_json),
    )
    return run_id


class TestBuildConversationContext:
    def test_excludes_non_terminal_sessions(self, client, tmp_path, app):
        """Only completed/failed sessions appear in context."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid, task="finished work", summary="all done",
                status="completed", started_at="2026-01-01T00:01:00",
            )
            _insert_completed_session(
                conn, pid, cid, task="running work", summary=None,
                status="running", started_at="2026-01-01T00:02:00",
            )
            _insert_completed_session(
                conn, pid, cid, task="stopped work", summary=None,
                status="stopped", started_at="2026-01-01T00:03:00",
            )
            _insert_completed_session(
                conn, pid, cid, task="stale work", summary=None,
                status="stale", started_at="2026-01-01T00:04:00",
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        assert "finished work" in ctx
        assert "running work" not in ctx
        assert "stopped work" not in ctx
        assert "stale work" not in ctx

    def test_uses_user_task_over_task(self, client, tmp_path, app):
        """Context uses user_task (raw input) instead of task (with nested context)."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="## Prior Conversation\n\nold stuff\n\n---\n\nactual request",
                user_task="actual request",
                summary="handled it",
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        assert "actual request" in ctx
        # The nested "## Prior Conversation" from task should NOT appear in the asked line
        assert "old stuff" not in ctx

    def test_strips_prior_context_when_user_task_is_null(self, client, tmp_path, app):
        """When user_task is NULL, strips context prefix from task."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="## Prior Conversation\n\nold\n\n---\n\nthe real task",
                user_task=None,
                summary="done",
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        assert "the real task" in ctx
        assert "old" not in ctx or "earlier turns omitted" in ctx

    def test_caps_at_max_turns(self, client, tmp_path, app):
        """Only the most recent 10 turns appear, with omission note."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            for i in range(15):
                _insert_completed_session(
                    conn, pid, cid,
                    task=f"task-{i:02d}", user_task=f"task-{i:02d}",
                    summary=f"result-{i:02d}",
                    started_at=f"2026-01-01T00:{i:02d}:00",
                )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        # Should have exactly 10 turns
        assert ctx.count("Turn ") == 10
        # Oldest 5 should be omitted
        assert "5 earlier turns omitted" in ctx
        assert "task-00" not in ctx
        assert "task-04" not in ctx
        # Most recent should be present
        assert "task-14" in ctx
        assert "task-05" in ctx

    def test_tiered_condensation(self, client, tmp_path, app):
        """Recent turns get more detail than old turns."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        long_summary = "A" * 250  # longer than old-turn limit (120), shorter than recent (300)

        with get_db(app.state.db_path) as conn:
            for i in range(6):
                _insert_completed_session(
                    conn, pid, cid,
                    task=f"task-{i}", user_task=f"task-{i}",
                    summary=long_summary,
                    started_at=f"2026-01-01T00:{i:02d}:00",
                )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        lines = [l for l in ctx.split("\n") if l.startswith("- Turn ")]
        # Turn 1-3 are old (4+ from end): summary should be truncated (has …)
        assert "…" in lines[0]
        # Turn 5 is recent (1 from end): summary should be full (no …)
        assert "…" not in lines[4]

    def test_pending_followup_capped(self, client, tmp_path, app):
        """Pending Follow-up is capped at 800 chars."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="big output task", user_task="big output task",
                summary="X" * 2000,
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        # Extract text after "**Pending Follow-up:**"
        followup = ctx.split("**Pending Follow-up:**\n")[1]
        assert len(followup) <= 810  # 800 + "…"

    def test_files_changed_shown_for_recent_turns(self, client, tmp_path, app):
        """File paths appear in context for recent turns only."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            for i in range(5):
                _insert_completed_session(
                    conn, pid, cid,
                    task=f"task-{i}", user_task=f"task-{i}",
                    summary=f"result-{i}",
                    started_at=f"2026-01-01T00:{i:02d}:00",
                    files_changed=[f"src/file_{i}.py"] if i >= 2 else None,
                )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        # Recent turns (last 3: turns 3, 4, 5) should show files
        assert "src/file_2.py" in ctx
        assert "src/file_3.py" in ctx
        assert "src/file_4.py" in ctx
        # Old turns (turns 1, 2) should NOT show files even if they had them
        lines = [l for l in ctx.split("\n") if l.startswith("- Turn ")]
        assert "files:" not in lines[0]  # Turn 1: no files_changed
        assert "files:" not in lines[1]  # Turn 2: no files_changed (old turn)

    def test_files_changed_caps_at_10(self, client, tmp_path, app):
        """File list is capped at 10 with a +N more indicator."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        many_files = [f"src/module_{i}.py" for i in range(15)]
        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="big change", user_task="big change",
                summary="done", files_changed=many_files,
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        assert "(+5 more)" in ctx
        assert "src/module_0.py" in ctx
        assert "src/module_9.py" in ctx
        assert "src/module_10.py" not in ctx
