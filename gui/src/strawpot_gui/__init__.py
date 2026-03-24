"""StrawPot GUI — local web dashboard for agent orchestration."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("strawpot-gui")
except PackageNotFoundError:
    __version__ = "0.0.0"
