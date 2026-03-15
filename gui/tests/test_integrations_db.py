"""Tests for integration database tables."""

from strawpot_gui.db import init_db, get_db


class TestIntegrationTables:
    """Verify integrations and integration_config tables exist and work."""

    def test_insert_integration(self, tmp_path):
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

    def test_integration_config(self, tmp_path):
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
            row = conn.execute(
                "SELECT value FROM integration_config "
                "WHERE integration_name = ? AND key = ?",
                ("telegram", "bot_token"),
            ).fetchone()
        assert row["value"] == "123:ABC"

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

    def test_integration_lifecycle_fields(self, tmp_path):
        """Test updating lifecycle fields (status, pid, started_at)."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO integrations (name) VALUES (?)",
                ("telegram",),
            )
            conn.execute(
                "UPDATE integrations SET status = ?, pid = ?, started_at = datetime('now') "
                "WHERE name = ?",
                ("running", 12345, "telegram"),
            )
            row = conn.execute(
                "SELECT status, pid, started_at FROM integrations WHERE name = ?",
                ("telegram",),
            ).fetchone()
        assert row["status"] == "running"
        assert row["pid"] == 12345
        assert row["started_at"] is not None
