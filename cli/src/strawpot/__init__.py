"""StrawPot — CLI for AI coding agent orchestration."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("strawpot")
except PackageNotFoundError:
    __version__ = "0.0.0"
