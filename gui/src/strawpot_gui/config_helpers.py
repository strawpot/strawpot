"""Shared config helpers for the GUI backend."""

import logging

from strawpot.config import load_config

logger = logging.getLogger(__name__)

# Last-resort fallback when the config file is unreadable (e.g., malformed TOML).
# Under normal operation, load_config(None) returns the StrawPotConfig dataclass
# default ("ai-ceo") if no orchestrator role is explicitly configured.
_FALLBACK_ROLE = "imu"


def default_orchestrator_role() -> str:
    """Read orchestrator role from global config.

    Returns the configured ``orchestrator.role`` value.  Falls back to
    ``"imu"`` only when the config file cannot be read (e.g. TOML parse
    error, missing file, or permission denied).  An empty-string role in
    the config is also treated as a fallback case.
    """
    try:
        role = load_config(None).orchestrator_role
        return role if role else _FALLBACK_ROLE
    except Exception:
        logger.warning("Failed to load global config for default role", exc_info=True)
        return _FALLBACK_ROLE
