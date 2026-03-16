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
                "SELECT name, status, auto_start FROM integrations WHERE name = ?",
                ("telegram",),
            ).fetchone()
        assert row["name"] == "telegram"
        assert row["status"] == "stopped"
        assert row["auto_start"] == 0

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
                "INSERT INTO integration_config (integration_name, key, value) "
                "VALUES (?, ?, ?)",
                ("telegram", "bot_token", "123:ABC"),
            )
            conn.execute(
                "DELETE FROM integrations WHERE name = ?",
                ("telegram",),
            )
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM integration_config "
                "WHERE integration_name = ?",
                ("telegram",),
            ).fetchone()
        assert count["cnt"] == 0

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
                "(integration_name, message) VALUES (?, ?)",
                ("telegram", "Hello"),
            )
            conn.execute(
                "DELETE FROM integrations WHERE name = ?",
                ("telegram",),
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
