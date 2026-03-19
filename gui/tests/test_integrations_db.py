"""Tests for integration database tables."""

from strawpot_gui.db import init_db, get_db


class TestIntegrationTables:
    """Verify integrations and integration_config tables exist and work."""

    def test_tables_exist(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO integrations (name) VALUES (?)",
                ("telegram",),
            )
            row = conn.execute(
                "SELECT name, project_id, status, auto_start FROM integrations WHERE name = ?",
                ("telegram",),
            ).fetchone()
        assert row["name"] == "telegram"
        assert row["project_id"] == 0
        assert row["status"] == "stopped"
        assert row["auto_start"] == 0

    def test_composite_primary_key(self, tmp_path):
        """Same integration name can exist for different projects."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO integrations (name, project_id) VALUES (?, ?)",
                ("telegram", 0),
            )
            conn.execute(
                "INSERT INTO integrations (name, project_id) VALUES (?, ?)",
                ("telegram", 1),
            )
            rows = conn.execute(
                "SELECT name, project_id FROM integrations WHERE name = ? ORDER BY project_id",
                ("telegram",),
            ).fetchall()
        assert len(rows) == 2
        assert rows[0]["project_id"] == 0
        assert rows[1]["project_id"] == 1

    def test_config_cascade_delete(self, tmp_path):
        """Deleting an integration cascades to its config rows."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO integrations (name) VALUES (?)",
                ("telegram",),
            )
            conn.execute(
                "INSERT INTO integration_config (integration_name, project_id, key, value) "
                "VALUES (?, ?, ?, ?)",
                ("telegram", 0, "bot_token", "123:ABC"),
            )
            conn.execute(
                "DELETE FROM integrations WHERE name = ? AND project_id = ?",
                ("telegram", 0),
            )
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM integration_config "
                "WHERE integration_name = ?",
                ("telegram",),
            ).fetchone()
        assert count["cnt"] == 0

    def test_config_cascade_delete_project_scoped(self, tmp_path):
        """Deleting a project-scoped integration only cascades its own config."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO integrations (name, project_id) VALUES (?, ?)",
                ("telegram", 0),
            )
            conn.execute(
                "INSERT INTO integrations (name, project_id) VALUES (?, ?)",
                ("telegram", 1),
            )
            conn.execute(
                "INSERT INTO integration_config (integration_name, project_id, key, value) "
                "VALUES (?, ?, ?, ?)",
                ("telegram", 0, "bot_token", "global_token"),
            )
            conn.execute(
                "INSERT INTO integration_config (integration_name, project_id, key, value) "
                "VALUES (?, ?, ?, ?)",
                ("telegram", 1, "bot_token", "project_token"),
            )
            # Delete only project 1's instance
            conn.execute(
                "DELETE FROM integrations WHERE name = ? AND project_id = ?",
                ("telegram", 1),
            )
            rows = conn.execute(
                "SELECT project_id, value FROM integration_config "
                "WHERE integration_name = ?",
                ("telegram",),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["project_id"] == 0
        assert rows[0]["value"] == "global_token"

    def test_notifications_cascade_delete(self, tmp_path):
        """Deleting an integration cascades to its notification rows."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO integrations (name) VALUES (?)",
                ("telegram",),
            )
            conn.execute(
                "INSERT INTO integration_notifications "
                "(integration_name, project_id, message) VALUES (?, ?, ?)",
                ("telegram", 0, "Hello"),
            )
            conn.execute(
                "DELETE FROM integrations WHERE name = ? AND project_id = ?",
                ("telegram", 0),
            )
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM integration_notifications "
                "WHERE integration_name = ?",
                ("telegram",),
            ).fetchone()
        assert count["cnt"] == 0


class TestScheduledTasksConversationId:
    """Verify conversation_id column on scheduled_tasks."""

    def test_conversation_id_column_exists(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, display_name, working_dir) "
                "VALUES (1, 'test', '/tmp/test')"
            )
            conn.execute(
                "INSERT INTO conversations (id, project_id) VALUES (10, 1)"
            )
            conn.execute(
                "INSERT INTO scheduled_tasks (name, project_id, task, conversation_id) "
                "VALUES (?, 1, 'do stuff', ?)",
                ("test-schedule", 10),
            )
            row = conn.execute(
                "SELECT conversation_id FROM scheduled_tasks WHERE name = ?",
                ("test-schedule",),
            ).fetchone()
        assert row["conversation_id"] == 10

    def test_conversation_id_nullable(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, display_name, working_dir) "
                "VALUES (1, 'test', '/tmp/test')"
            )
            conn.execute(
                "INSERT INTO scheduled_tasks (name, project_id, task) "
                "VALUES (?, 1, 'do stuff')",
                ("test-schedule",),
            )
            row = conn.execute(
                "SELECT conversation_id FROM scheduled_tasks WHERE name = ?",
                ("test-schedule",),
            ).fetchone()
        assert row["conversation_id"] is None
