"""Cross-platform process utilities."""

import os
import sys


def is_pid_alive(pid: int) -> bool:
    """Check if a process is still running (cross-platform).

    On Windows, uses kernel32.OpenProcess. On Unix, uses ``os.kill(pid, 0)``.
    """
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it
    return True
