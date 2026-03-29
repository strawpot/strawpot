"""Parse real-time activity from agent log output.

Reads the tail of agent ``.log`` files and extracts human-readable
activity descriptions (e.g. "Reading src/app.ts", "Running tests").
Used by the activity watcher thread to emit ``tool_start`` /
``tool_end`` trace events so the GUI can display live agent status.
"""

import os
import re
from dataclasses import dataclass

# ANSI escape sequence pattern
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Braille spinner characters used by Claude Code and similar CLIs
_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏•·…● "

# Patterns that map log output to structured (tool, summary) pairs.
# Order matters — first match wins.
_TOOL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Claude Code tool patterns (spinner + tool description)
    (re.compile(r"(?i)reading\s+(.+?)\.{0,3}$"), "Read"),
    (re.compile(r"(?i)editing\s+(.+?)\.{0,3}$"), "Edit"),
    (re.compile(r"(?i)writing\s+(?:to\s+)?(.+?)\.{0,3}$"), "Write"),
    (re.compile(r"(?i)searching\s+(.+?)\.{0,3}$"), "Search"),
    (re.compile(r"(?i)running\s+(?:bash\s+)?(?:command:?\s*)?(.+?)\.{0,3}$"), "Bash"),
    (re.compile(r"(?i)executing\s+(.+?)\.{0,3}$"), "Bash"),
    (re.compile(r"(?i)(?:launching|spawning)\s+(?:agent\s+)?(.+?)\.{0,3}$"), "Agent"),
    (re.compile(r"(?i)thinking\.{0,3}$"), "Think"),
    (re.compile(r"(?i)planning\.{0,3}$"), "Think"),
]


@dataclass
class ActivityInfo:
    """Structured activity parsed from a log line."""

    tool: str       # "Read", "Edit", "Write", "Bash", "Search", "Agent", "Think", "Tool"
    summary: str    # Full human-readable string (e.g. "Reading src/app.ts")
    target: str     # Extracted target (e.g. "src/app.ts"), empty if none


def _clean_line(line: str) -> str | None:
    """Strip ANSI codes and spinner characters.  Returns None if empty."""
    if not line:
        return None
    clean = _ANSI_RE.sub("", line).strip()
    stripped = clean.lstrip(_SPINNER_CHARS).strip()
    return stripped or None


def parse_activity(line: str) -> tuple[str, str] | None:
    """Extract ``(tool, summary)`` from a single log line.

    Returns ``None`` when no recognisable activity is found.

    The *tool* is a short identifier (``"Read"``, ``"Edit"``, etc.)
    and *summary* is the cleaned human-readable description suitable
    for display in the GUI.
    """
    stripped = _clean_line(line)
    if stripped is None:
        return None

    # Try structured patterns first
    for pattern, tool in _TOOL_PATTERNS:
        m = pattern.search(stripped)
        if m:
            summary = stripped
            # Truncate long summaries
            if len(summary) > 120:
                summary = summary[:117] + "..."
            return tool, summary

    # Fallback: lines ending with "..." or "…" look like progress
    # indicators — treat as generic activity.
    if len(stripped) <= 120 and (
        stripped.endswith("...") or stripped.endswith("…")
    ):
        return "Tool", stripped

    return None


def parse_activity_structured(line: str) -> ActivityInfo | None:
    """Like :func:`parse_activity` but returns structured :class:`ActivityInfo`.

    The ``target`` field is extracted from regex capture groups where
    available (e.g. ``"Reading src/app.ts"`` → ``target="src/app.ts"``).
    Patterns without capture groups (Think, Planning) have an empty target.
    """
    stripped = _clean_line(line)
    if stripped is None:
        return None

    for pattern, tool in _TOOL_PATTERNS:
        m = pattern.search(stripped)
        if m:
            summary = stripped
            if len(summary) > 120:
                summary = summary[:117] + "..."
            # Extract target from first capture group if present
            target = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
            return ActivityInfo(tool=tool, summary=summary, target=target)

    # Fallback: generic activity
    if len(stripped) <= 120 and (
        stripped.endswith("...") or stripped.endswith("…")
    ):
        return ActivityInfo(tool="Tool", summary=stripped, target="")

    return None


def read_last_activity_line(log_path: str) -> str | None:
    """Read the last non-empty line from an agent log file.

    Reads up to the last 4 KB to find the final line efficiently.
    Returns ``None`` if the file is empty or unreadable.
    """
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return None
            chunk_size = min(4096, size)
            f.seek(size - chunk_size)
            data = f.read(chunk_size).decode("utf-8", errors="replace")
            lines = data.strip().splitlines()
            return lines[-1].strip() if lines else None
    except OSError:
        return None


def get_agent_log_path(session_dir: str, agent_id: str) -> str:
    """Return the path to an agent's ``.log`` file."""
    return os.path.join(session_dir, "agents", agent_id, ".log")
