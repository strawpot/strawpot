"""Process utilities for Linux and macOS."""

import os
import signal
import shutil
import stat
import sys


def robust_rmtree(path: str) -> None:
    """Remove a directory tree, handling read-only files.

    Git directories can contain read-only objects that cause
    ``shutil.rmtree`` to fail.  This wrapper clears the read-only flag
    before retrying the removal.
    """

    def _fix_permissions(func, fpath, _exc):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_fix_permissions)
    else:
        shutil.rmtree(
            path, onerror=lambda f, p, e: _fix_permissions(f, p, e[1])
        )


def is_pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it
    return True


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its children.

    Kills the process group (created by ``start_new_session=True``
    in Popen) via ``os.killpg``, falling back to ``os.kill``.
    """
    # Kill the process group so children are also terminated.
    # Only use killpg when the target has its own process group
    # (start_new_session=True); otherwise we'd kill our own group.
    try:
        target_pgid = os.getpgid(pid)
        if target_pgid != os.getpgid(os.getpid()):
            os.killpg(target_pgid, signal.SIGTERM)
            return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    # Fallback: kill just the process
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
