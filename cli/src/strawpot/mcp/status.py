"""MCP configuration status detection."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from strawpot.mcp.setup import _SERVER_NAME, _global_config_candidates, _project_config_path

log = logging.getLogger(__name__)


def check_mcp_status() -> tuple[bool, str]:
    """Check if StrawPot MCP memory server is configured for Claude Code.

    Returns:
        (is_configured, config_path_str)
    """
    # Check project-level first
    project_path = _project_config_path()
    if _has_server_entry(project_path):
        return True, str(project_path)

    # Check global config candidates
    for candidate in _global_config_candidates():
        if _has_server_entry(candidate):
            return True, str(candidate)

    return False, ""


def _has_server_entry(path: Path) -> bool:
    """Check if a config file has the strawpot-memory MCP entry."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _SERVER_NAME in data.get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        return False
