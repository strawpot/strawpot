"""Shared config helpers for the GUI backend."""

import logging
import sqlite3

from strawpot.config import get_strawpot_home, load_config

logger = logging.getLogger(__name__)

# Last-resort fallback when the config file is unreadable (e.g., malformed TOML).
# Under normal operation, load_config(None) returns the StrawPotConfig dataclass
# default ("ai-ceo") if no orchestrator role is explicitly configured.
_FALLBACK_ROLE = "imu"


def _read_setting_from_db(key: str) -> str | None:
    """Read a single setting from the GUI database, or None if unavailable."""
    db_path = get_strawpot_home() / "gui.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        return row["value"] if row else None
    except Exception:
        logger.debug("Could not read setting %r from DB", key, exc_info=True)
        return None


def default_orchestrator_role() -> str:
    """Read orchestrator role with priority: DB → TOML → fallback.

    1. Check ``settings`` table for ``orchestrator_role`` (set by ImuPage).
    2. Fall back to ``orchestrator.role`` in global ``strawpot.toml``.
    3. Last resort: ``"imu"``.
    """
    # 1. DB setting (highest priority — set directly by the user via GUI)
    db_role = _read_setting_from_db("orchestrator_role")
    if db_role:
        return db_role

    # 2. TOML config
    try:
        role = load_config(None).orchestrator_role
        if role:
            return role
    except Exception:
        logger.warning("Failed to load global config for default role", exc_info=True)

    return _FALLBACK_ROLE
