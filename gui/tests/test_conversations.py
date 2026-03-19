"""Tests for conversation endpoints."""

import uuid
from unittest.mock import patch

from test_sessions_sync import _register_project

from strawpot_gui.db import _extract_recap, _normalize_recap_marker, _strip_recap, get_db
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

    def test_pagination_limit(self, client, tmp_path, app):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]
        with get_db(app.state.db_path) as conn:
            for i in range(3):
                _insert_completed_session(
                    conn, pid, cid, task=f"task-{i}",
                    started_at=f"2026-01-01T00:{i:02d}:00",
                )
        data = client.get(f"/api/conversations/{cid}?limit=2").json()
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

    def test_summary_strips_recap(self, app, client, tmp_path):
        """Session recap block is stripped from summary in API response."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        summary = "Built the login page.\n\n## Session Recap\n### Accomplished\n- Login page done"
        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="build login", user_task="build login",
                summary=summary,
            )

        data = client.get(f"/api/conversations/{cid}").json()
        returned_summary = data["sessions"][0]["summary"]
        assert "## Session Recap" not in returned_summary
        assert "Built the login page." in returned_summary


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

    def test_passes_group_id_to_cli(self, client, tmp_path):
        """The subprocess command includes --group-id with the conversation ID."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        body = {"task": "Build it"}
        with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
             patch("strawpot_gui.routers.sessions.subprocess.Popen") as mock_popen, \
             patch("strawpot_gui.routers.sessions.load_config") as mock_config:
            from strawpot.config import StrawPotConfig
            mock_config.return_value = StrawPotConfig()
            resp = client.post(f"/api/conversations/{cid}/tasks", json=body)

        assert resp.status_code == 201
        cmd = mock_popen.call_args[0][0]
        assert "--group-id" in cmd
        idx = cmd.index("--group-id")
        assert cmd[idx + 1] == str(cid)


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
    session_dir=None, interactive=False,
):
    """Insert a session row directly for testing context building."""
    run_id = uuid.uuid4().hex[:12]
    if started_at is None:
        started_at = "2026-01-01T00:00:00"
    if session_dir is None:
        session_dir = f"/tmp/{run_id}"
    import json as _json
    fc_json = _json.dumps(files_changed) if files_changed else None
    conn.execute(
        "INSERT INTO sessions "
        "(run_id, project_id, role, runtime, isolation, status, task, user_task, "
        "summary, exit_code, conversation_id, started_at, session_dir, "
        "files_changed, interactive) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, project_id, "default", "claude-code", "none", status, task,
         user_task, summary, exit_code, conversation_id, started_at,
         session_dir, fc_json, int(interactive)),
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

        result_lines = [l for l in ctx.split("\n") if l.startswith("- Result: ")]
        # Turn 1-3 are old (4+ from end): summary should be truncated (has …)
        assert "…" in result_lines[0]
        # Turn 5 is recent (1 from end): summary should be full (no …)
        assert "…" not in result_lines[4]

    def test_pending_followup_no_recap_capped(self, client, tmp_path, app):
        """Pending Follow-up without recap section is capped at 2000 chars."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="big output task", user_task="big output task",
                summary="X" * 5000,
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        # Extract text after "**Pending Follow-up:**"
        followup = ctx.split("**Pending Follow-up:**\n")[1]
        assert len(followup) <= 2010  # 2000 + "…"

    def test_pending_followup_dual_with_recap(self, client, tmp_path, app):
        """When recap exists, Pending Follow-up shows both recap and recent output."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        summary = (
            "I implemented the login page and added tests.\n\n"
            "## Session Recap\n"
            "### Accomplished\n- Built login page\n"
            "### Decisions\n- Chose JWT"
        )
        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="build login", user_task="build login",
                summary=summary,
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        assert "**Recap:**" in ctx
        assert "Built login page" in ctx
        assert "**Recent output:**" in ctx
        assert "I implemented the login page" in ctx

    def test_pending_followup_recap_capped(self, client, tmp_path, app):
        """Recap section in Pending Follow-up is capped at 1500 chars."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        long_recap = "A" * 3000
        summary = f"short output\n\n## Session Recap\n{long_recap}"
        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="task", user_task="task",
                summary=summary,
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        recap_section = ctx.split("**Recap:**\n")[1].split("\n\n**Recent output:**")[0]
        assert len(recap_section) <= 1510  # 1500 + "…"

    def test_pending_followup_raw_tail_capped(self, client, tmp_path, app):
        """Raw output tail in Pending Follow-up is capped at 1500 chars."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        long_output = "B" * 5000
        summary = f"{long_output}\n\n## Session Recap\n- done"
        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="task", user_task="task",
                summary=summary,
            )

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        raw_section = ctx.split("**Recent output:**\n")[1]
        assert len(raw_section) <= 1500

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
        turn_headers = [l for l in ctx.split("\n") if l.startswith("**Turn ")]
        assert "files:" not in turn_headers[0]  # Turn 1: no files_changed
        assert "files:" not in turn_headers[1]  # Turn 2: no files_changed (old turn)

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

    def test_no_context_when_no_prior_sessions(self, client, tmp_path, app):
        """When there are no prior sessions, context is empty."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            ctx = _build_conversation_context(conn, cid)

        assert ctx == ""


class TestExtractRecap:
    def test_extracts_recap_block(self):
        content = (
            "I did a bunch of work.\n\n"
            "## Session Recap\n"
            "- Implemented the login page\n"
            "- User chose JWT over sessions\n"
            "- Open: need to add tests"
        )
        result = _extract_recap(content)
        assert result.startswith("- Implemented the login page")
        assert "Open: need to add tests" in result
        assert "I did a bunch of work" not in result

    def test_returns_full_content_when_no_recap(self):
        content = "Just some regular output with no recap section."
        assert _extract_recap(content) == content

    def test_uses_last_occurrence(self):
        content = (
            "## Session Recap\nfirst recap\n\n"
            "more output\n\n"
            "## Session Recap\n- actual recap"
        )
        result = _extract_recap(content)
        assert result == "- actual recap"

    def test_empty_recap_returns_full_content(self):
        content = "some output\n\n## Session Recap\n"
        assert _extract_recap(content) == content

    def test_bold_marker(self):
        content = (
            "Here is the output.\n\n"
            "**Session Recap**\n\n"
            "### Accomplished\n- Did things"
        )
        result = _extract_recap(content)
        assert result.startswith("### Accomplished")
        assert "Here is the output" not in result


class TestStripRecap:
    def test_strips_recap_block(self):
        content = (
            "I did a bunch of work.\n\n"
            "## Session Recap\n"
            "- Implemented the login page"
        )
        result = _strip_recap(content)
        assert result == "I did a bunch of work."
        assert "Session Recap" not in result

    def test_returns_full_content_when_no_recap(self):
        content = "Just some regular output."
        assert _strip_recap(content) == content

    def test_uses_last_occurrence(self):
        content = (
            "## Session Recap\nfirst recap\n\n"
            "more output\n\n"
            "## Session Recap\n- actual recap"
        )
        result = _strip_recap(content)
        assert "more output" in result
        assert "actual recap" not in result

    def test_returns_full_content_when_only_recap(self):
        content = "## Session Recap\n- Implemented the login page"
        result = _strip_recap(content)
        assert result == content

    def test_bold_marker(self):
        content = (
            "Here is the output.\n\n"
            "**Session Recap**\n\n"
            "### Accomplished\n- Did things"
        )
        result = _strip_recap(content)
        assert result == "Here is the output."
        assert "Session Recap" not in result


class TestNormalizeRecapMarker:
    def test_replaces_bold_with_heading(self):
        content = "Output\n\n**Session Recap**\n\n- Did things"
        result = _normalize_recap_marker(content)
        assert "**Session Recap**" not in result
        assert "## Session Recap" in result

    def test_leaves_heading_unchanged(self):
        content = "Output\n\n## Session Recap\n\n- Did things"
        result = _normalize_recap_marker(content)
        assert result == content

    def test_no_recap(self):
        content = "Just output, no recap."
        assert _normalize_recap_marker(content) == content


class TestHistoryFileHint:
    def test_hint_included_when_path_provided(self, client, tmp_path, app):
        """Context includes history file hint when history_path is given."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="first", user_task="first", summary="done",
            )
            ctx = _build_conversation_context(
                conn, cid, history_path="/tmp/test/conversation_history.md"
            )

        assert "/tmp/test/conversation_history.md" in ctx
        assert "read it if you need more detail" in ctx

    def test_no_hint_when_path_is_none(self, client, tmp_path, app):
        """Context omits history file hint when history_path is None."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="first", user_task="first", summary="done",
            )
            ctx = _build_conversation_context(conn, cid)

        assert "conversation_history.md" not in ctx


class TestMessageQueuing:
    """Tests for pending_task message queuing."""

    def test_queues_when_session_active(self, client, tmp_path, app):
        """Submitting while a session is active returns 202 and queues the task."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        # First task launches normally (201)
        resp1 = _submit_task(client, cid, task="First task")
        assert resp1.status_code == 201

        # Session is still "starting" — second task should be queued (202)
        resp2 = _submit_task(client, cid, task="Second task")
        assert resp2.status_code == 202
        assert resp2.json()["queued"] is True

        # Verify pending_task is stored
        data = client.get(f"/api/conversations/{cid}").json()
        assert data["pending_task"] == "Second task"

    def test_queued_tasks_concatenate(self, client, tmp_path, app):
        """Multiple queued tasks are concatenated."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="First task")
        _submit_task(client, cid, task="Task A")
        _submit_task(client, cid, task="Task B")

        data = client.get(f"/api/conversations/{cid}").json()
        assert "Task A" in data["pending_task"]
        assert "Task B" in data["pending_task"]

    def test_cancel_pending_task(self, client, tmp_path, app):
        """DELETE /conversations/{id}/pending_task clears the queue."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="First task")
        _submit_task(client, cid, task="Queued task")

        resp = client.delete(f"/api/conversations/{cid}/pending_task")
        assert resp.status_code == 204

        data = client.get(f"/api/conversations/{cid}").json()
        assert data["pending_task"] is None

    def test_cancel_pending_task_404(self, client):
        """Cancel on non-existent conversation returns 404."""
        resp = client.delete("/api/conversations/9999/pending_task")
        assert resp.status_code == 404

    def test_pending_task_null_when_no_queue(self, client, tmp_path):
        """Conversation without queued tasks has pending_task = null."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        data = client.get(f"/api/conversations/{conv['id']}").json()
        assert data["pending_task"] is None

    def test_auto_submit_drains_pending_on_completion(self, client, tmp_path, app):
        """When a session completes and a task is queued, a new session is launched."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        # Launch first task
        resp1 = _submit_task(client, cid, task="First task")
        run_id1 = resp1.json()["run_id"]

        # Queue a second task
        _submit_task(client, cid, task="Auto-submit me")

        # Verify task is in the queue table
        with get_db(app.state.db_path) as conn:
            queued = conn.execute(
                "SELECT task, source FROM conversation_task_queue WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        assert len(queued) == 1
        assert queued[0]["task"] == "Auto-submit me"
        assert queued[0]["source"] == "user"

        # Simulate session completion by calling _drain_pending_task
        from strawpot_gui.routers.sessions import _drain_pending_task
        with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
             patch("strawpot_gui.routers.sessions.subprocess.Popen"), \
             patch("strawpot_gui.routers.sessions.load_config") as mock_config:
            from strawpot.config import StrawPotConfig
            mock_config.return_value = StrawPotConfig()
            with get_db(app.state.db_path) as conn:
                # Mark first session as completed
                conn.execute(
                    "UPDATE sessions SET status = 'completed', exit_code = 0 WHERE run_id = ?",
                    (run_id1,),
                )
                _drain_pending_task(conn, cid)

        # Queue should be empty after drain
        with get_db(app.state.db_path) as conn:
            remaining = conn.execute(
                "SELECT id FROM conversation_task_queue WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        assert len(remaining) == 0

        # A new session should have been created
        with get_db(app.state.db_path) as conn:
            sessions = conn.execute(
                "SELECT run_id FROM sessions WHERE conversation_id = ?", (cid,)
            ).fetchall()
        assert len(sessions) == 2  # original + auto-submitted


class TestWriteConversationHistory:
    def test_writes_history_file(self, client, tmp_path, app):
        """History file is written with full output for recent turns."""
        from strawpot_gui.routers.conversations import _write_conversation_history

        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="implement login", user_task="implement login",
                summary="Built the login page with JWT auth.",
                started_at="2026-01-01T10:00:00",
                files_changed=["src/login.tsx"],
            )
            path = _write_conversation_history(conn, cid, str(d))

        assert path is not None
        content = open(path).read()
        assert "# Conversation History" in content
        assert "implement login" in content
        assert "Built the login page with JWT auth." in content
        assert "src/login.tsx" in content

    def test_returns_none_when_no_sessions(self, client, tmp_path, app):
        """Returns None when there are no completed sessions."""
        from strawpot_gui.routers.conversations import _write_conversation_history

        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            path = _write_conversation_history(conn, cid, str(d))

        assert path is None

    def test_recent_turns_full_output_older_turns_recap(self, client, tmp_path, app):
        """Last 5 turns get full output; older turns get recap only."""
        from strawpot_gui.routers.conversations import _write_conversation_history

        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            for i in range(8):
                full_output = f"FULL_OUTPUT_{i} detailed work here"
                recap = f"RECAP_ONLY_{i}"
                summary = f"{full_output}\n\n## Session Recap\n{recap}"
                _insert_completed_session(
                    conn, pid, cid,
                    task=f"task-{i}", user_task=f"task-{i}",
                    summary=summary,
                    started_at=f"2026-01-01T00:{i:02d}:00",
                )
            path = _write_conversation_history(conn, cid, str(d))

        content = open(path).read()
        # Turns 1-3 (old, 5+ from end): recap only, no full output
        assert "FULL_OUTPUT_0" not in content
        assert "RECAP_ONLY_0" in content
        assert "FULL_OUTPUT_2" not in content
        assert "RECAP_ONLY_2" in content
        # Turns 4-8 (recent, last 5): full output present
        assert "FULL_OUTPUT_3" in content
        assert "FULL_OUTPUT_7" in content

    def test_caps_at_10_turns(self, client, tmp_path, app):
        """History file includes at most 10 turns."""
        from strawpot_gui.routers.conversations import _write_conversation_history

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
            path = _write_conversation_history(conn, cid, str(d))

        content = open(path).read()
        assert content.count("## Turn ") == 10
        assert "5 earlier turns omitted" in content
        assert "task-00" not in content
        assert "task-14" in content


    def test_history_file_scoped_to_conversation_id(self, client, tmp_path, app):
        """Each conversation writes to its own history file."""
        from strawpot_gui.routers.conversations import _write_conversation_history

        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv_a = _create_conversation(client, pid)
        conv_b = _create_conversation(client, pid)
        cid_a = conv_a["id"]
        cid_b = conv_b["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid_a,
                task="auth work", user_task="auth work",
                summary="Built auth.",
            )
            _insert_completed_session(
                conn, pid, cid_b,
                task="css fix", user_task="css fix",
                summary="Fixed CSS.",
            )
            path_a = _write_conversation_history(conn, cid_a, str(d))
            path_b = _write_conversation_history(conn, cid_b, str(d))

        # Different files
        assert path_a != path_b
        assert path_a.endswith(f"conversations/{cid_a}/history.md")
        assert path_b.endswith(f"conversations/{cid_b}/history.md")

        # Each file contains only its own conversation's content
        content_a = open(path_a).read()
        content_b = open(path_b).read()
        assert "auth work" in content_a
        assert "css fix" not in content_a
        assert "css fix" in content_b
        assert "auth work" not in content_b


class TestChatMessagePersistence:
    """Tests for chat message persistence in conversation responses."""

    def test_interactive_session_includes_chat_messages(self, client, tmp_path, app):
        """Interactive sessions with chat_messages.jsonl return messages in API."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        # Create a session dir with chat_messages.jsonl
        import json as _json
        session_dir = tmp_path / "session_with_chat"
        session_dir.mkdir()
        messages = [
            {"id": "req_1", "role": "agent", "text": "What color?", "timestamp": 1000.0},
            {"id": "user-req_1", "role": "user", "text": "Blue", "timestamp": 1001.0},
        ]
        with open(session_dir / "chat_messages.jsonl", "w") as f:
            for msg in messages:
                f.write(_json.dumps(msg) + "\n")

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="interactive task", user_task="interactive task",
                summary="done",
                session_dir=str(session_dir),
                interactive=True,
            )

        data = client.get(f"/api/conversations/{cid}").json()
        session = data["sessions"][0]
        assert session["interactive"] is True
        assert len(session["chat_messages"]) == 2
        assert session["chat_messages"][0]["text"] == "What color?"
        assert session["chat_messages"][1]["text"] == "Blue"

    def test_non_interactive_session_has_no_chat_messages(self, client, tmp_path, app):
        """Non-interactive sessions do not include chat_messages field."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="normal task", user_task="normal task",
                summary="done",
            )

        data = client.get(f"/api/conversations/{cid}").json()
        session = data["sessions"][0]
        assert session.get("interactive") is False
        assert "chat_messages" not in session

    def test_interactive_session_without_chat_file_returns_empty(self, client, tmp_path, app):
        """Interactive session with no chat_messages.jsonl returns empty list."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        session_dir = tmp_path / "session_no_chat"
        session_dir.mkdir()

        with get_db(app.state.db_path) as conn:
            _insert_completed_session(
                conn, pid, cid,
                task="interactive no chat", user_task="interactive no chat",
                summary="done",
                session_dir=str(session_dir),
                interactive=True,
            )

        data = client.get(f"/api/conversations/{cid}").json()
        session = data["sessions"][0]
        assert session["interactive"] is True
        assert session["chat_messages"] == []

    def test_chat_messages_preserved_across_multiple_sessions(self, client, tmp_path, app):
        """Each interactive session keeps its own chat messages."""
        import json as _json
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        for i in range(2):
            session_dir = tmp_path / f"session_{i}"
            session_dir.mkdir()
            msgs = [{"id": f"q_{i}", "role": "agent", "text": f"Question {i}", "timestamp": float(1000 + i)}]
            with open(session_dir / "chat_messages.jsonl", "w") as f:
                f.write(_json.dumps(msgs[0]) + "\n")

            with get_db(app.state.db_path) as conn:
                _insert_completed_session(
                    conn, pid, cid,
                    task=f"task-{i}", user_task=f"task-{i}",
                    summary=f"done-{i}",
                    started_at=f"2026-01-01T00:0{i}:00",
                    session_dir=str(session_dir),
                    interactive=True,
                )

        data = client.get(f"/api/conversations/{cid}").json()
        assert len(data["sessions"]) == 2
        assert data["sessions"][0]["chat_messages"][0]["text"] == "Question 0"
        assert data["sessions"][1]["chat_messages"][0]["text"] == "Question 1"


class TestConversationCrossLinks:
    """Tests for parent/child conversation linking."""

    def test_create_with_parent_conversation_id(self, client, tmp_path):
        """Create a conversation with a parent link."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        # Create parent (imu) conversation
        parent = client.post("/api/imu/conversations").json()

        # Create child with parent_conversation_id
        resp = client.post("/api/conversations", json={
            "project_id": pid,
            "title": "Fix bug",
            "parent_conversation_id": parent["id"],
        })
        assert resp.status_code == 201
        assert resp.json()["parent_conversation_id"] == parent["id"]

    def test_get_conversation_includes_parent(self, client, tmp_path):
        """GET conversation returns parent info."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        parent = client.post("/api/imu/conversations").json()
        child = client.post("/api/conversations", json={
            "project_id": pid,
            "parent_conversation_id": parent["id"],
        }).json()

        data = client.get(f"/api/conversations/{child['id']}").json()
        assert data["parent"] is not None
        assert data["parent"]["id"] == parent["id"]
        assert data["parent"]["project_name"] == "Bot Imu"

    def test_get_conversation_includes_children(self, client, tmp_path):
        """GET parent conversation returns children."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        parent = client.post("/api/imu/conversations").json()
        child = client.post("/api/conversations", json={
            "project_id": pid,
            "title": "Delegated work",
            "parent_conversation_id": parent["id"],
        }).json()

        data = client.get(f"/api/conversations/{parent['id']}").json()
        assert len(data["children"]) == 1
        assert data["children"][0]["id"] == child["id"]
        assert data["children"][0]["title"] == "Delegated work"

    def test_no_parent_returns_null(self, client, tmp_path):
        """Conversation without parent has parent=null and children=[]."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)

        data = client.get(f"/api/conversations/{conv['id']}").json()
        assert data["parent"] is None
        assert data["children"] == []

    def test_invalid_parent_returns_422(self, client, tmp_path):
        """Creating with nonexistent parent returns 422."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        resp = client.post("/api/conversations", json={
            "project_id": pid,
            "parent_conversation_id": 99999,
        })
        assert resp.status_code == 422

    def test_parent_deleted_sets_null(self, client, tmp_path, app):
        """Deleting parent sets child's parent_conversation_id to NULL."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        parent = client.post("/api/imu/conversations").json()
        child = client.post("/api/conversations", json={
            "project_id": pid,
            "parent_conversation_id": parent["id"],
        }).json()

        # Delete parent
        client.delete(f"/api/conversations/{parent['id']}")

        # Child's parent should be null
        data = client.get(f"/api/conversations/{child['id']}").json()
        assert data["parent_conversation_id"] is None
        assert data["parent"] is None

    def test_list_project_conversations_includes_parent_id(self, client, tmp_path):
        """Project conversation list includes parent_conversation_id."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        parent = client.post("/api/imu/conversations").json()
        client.post("/api/conversations", json={
            "project_id": pid,
            "parent_conversation_id": parent["id"],
        })

        items = client.get(f"/api/projects/{pid}/conversations").json()["items"]
        assert len(items) == 1
        assert items[0]["parent_conversation_id"] == parent["id"]

    def test_imu_list_includes_spawned_count(self, client, tmp_path):
        """Imu conversation list includes spawned_count."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        parent = client.post("/api/imu/conversations").json()
        client.post("/api/conversations", json={
            "project_id": pid,
            "parent_conversation_id": parent["id"],
        })
        client.post("/api/conversations", json={
            "project_id": pid,
            "parent_conversation_id": parent["id"],
        })

        items = client.get("/api/imu/conversations").json()
        conv = next(c for c in items if c["id"] == parent["id"])
        assert conv["spawned_count"] == 2
