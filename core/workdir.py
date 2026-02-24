"""Project working directory resolution.

Every ``lt`` command that operates on a project resolves the working directory
automatically — no ``--project`` flag needed:

1. If ``$LT_WORKDIR`` is set, use that path.
2. Otherwise, walk up from ``$CWD`` until a ``.strawpot/`` directory is found
   (same as how ``git`` locates ``.git/``).
3. If neither is found, raise :class:`WorkdirError`.
"""

from __future__ import annotations

import os
from pathlib import Path


class WorkdirError(Exception):
    """Raised when no strawpot project directory can be resolved."""


def resolve_workdir(cwd: Path | None = None) -> Path:
    """Return the strawpot project root for the current session.

    Priority:
    1. ``$LT_WORKDIR`` environment variable — used by scripts/CI.
    2. Walk up from *cwd* (defaults to ``Path.cwd()``) looking for
       ``.strawpot/``.

    Raises:
        WorkdirError: if no project directory can be found.
    """
    lt_workdir = os.environ.get("LT_WORKDIR")
    if lt_workdir:
        p = Path(lt_workdir).resolve()
        if not (p / ".strawpot").is_dir():
            raise WorkdirError(
                f"$LT_WORKDIR={lt_workdir!r} does not contain a .strawpot/ directory"
            )
        return p

    start = (cwd or Path.cwd()).resolve()
    current = start
    while True:
        if (current / ".strawpot").is_dir():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    raise WorkdirError(
        "not in a strawpot project (no .strawpot/ found)\n"
        "Run 'lt init' to initialise a project here, or set $LT_WORKDIR."
    )
