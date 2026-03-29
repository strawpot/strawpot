"""Parse real-time activity from agent log output.

Reads the tail of agent ``.log`` files and extracts human-readable
activity descriptions (e.g. "Reading src/app.ts", "Running tests").
Used by the activity watcher thread to emit ``tool_start`` /
``tool_end`` trace events so the GUI can display live agent status.
"""

import os
import re

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


def parse_activity(line: str) -> tuple[str, str] | None:
    """Extract ``(tool, summary)`` from a single log line.

    Returns ``None`` when no recognisable activity is found.

    The *tool* is a short identifier (``"Read"``, ``"Edit"``, etc.)
    and *summary* is the cleaned human-readable description suitable
    for display in the GUI.
    """
    if not line:
        return None

    # Strip ANSI escape codes
    clean = _ANSI_RE.sub("", line).strip()

    # Strip leading spinner characters
    stripped = clean.lstrip(_SPINNER_CHARS).strip()
    if not stripped:
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
