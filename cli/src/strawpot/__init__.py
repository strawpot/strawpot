"""StrawPot — lightweight CLI for agent orchestration."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("strawpot")
except PackageNotFoundError:
    __version__ = "0.0.0"
