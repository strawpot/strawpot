"""Prerequisite checker for StrawPot (``strawpot doctor``)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    """Result of a single prerequisite check.

    ``passed`` is ``True`` when the check succeeded.  For tool checks this
    means the tool is on PATH and meets any minimum-version constraint.
    For env-var checks it means the variable is set.

    Use ``path`` to distinguish *missing* (``path is None``) from
    *wrong version* (``path`` set, ``passed`` is ``False``).
    """

    name: str
    description: str
    passed: bool
    version: str | None = None
    path: str | None = None
    required: bool = True
    hint: str = ""


@dataclass
class DoctorReport:
    """Aggregated results from all prerequisite checks."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if not self.checks:
            return False
        return all(c.passed for c in self.checks if c.required)

    @property
    def missing_required(self) -> list[CheckResult]:
        return [c for c in self.checks if c.required and not c.passed]

    @property
    def missing_optional(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.required and not c.passed]


def _get_version(cmd: str, args: tuple[str, ...] = ("--version",)) -> str | None:
    """Run ``cmd --version`` and return the first version-like match."""
    path = shutil.which(cmd)
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout.strip() or result.stderr.strip()
        match = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", output)
        return match.group(1) if match else None
    except (subprocess.SubprocessError, OSError):
        return None


def _version_at_least(version: str | None, minimum: str) -> bool:
    """Return True if *version* >= *minimum* using segment-wise comparison."""
    if version is None:
        return False
    try:
        v_parts = [int(x) for x in version.split(".")]
        m_parts = [int(x) for x in minimum.split(".")]
        return v_parts >= m_parts
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Prerequisite definitions
# ---------------------------------------------------------------------------
# Each tuple: (command, description, install_hint, required, min_version)

_PREREQUISITES: list[tuple[str, str, str, bool, str | None]] = [
    (
        "python3",
        "Python 3.11+",
        "https://python.org",
        True,
        "3.11",
    ),
    (
        "pip3",
        "pip (Python package manager)",
        "python3 -m ensurepip or https://pip.pypa.io",
        True,
        None,
    ),
    (
        "node",
        "Node.js 18+ (required by Claude Code)",
        "https://nodejs.org",
        True,
        "18",
    ),
    (
        "npm",
        "npm (ships with Node.js)",
        "https://nodejs.org",
        True,
        None,
    ),
    (
        "git",
        "git (worktree skill, PR workflows)",
        "https://git-scm.com",
        True,
        None,
    ),
    (
        "gh",
        "GitHub CLI (for PR creation)",
        "https://cli.github.com",
        False,
        None,
    ),
    (
        "curl",
        "curl (optional, install scripts can use Python)",
        "Install via your package manager",
        False,
        None,
    ),
]

# Environment variables to check (all informational, none required)
_ENV_VARS: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY", "Anthropic API key (for Claude)"),
    ("OPENAI_API_KEY", "OpenAI API key (for Codex)"),
    ("GITHUB_TOKEN", "GitHub token (for PR workflows)"),
]


def check_prerequisites() -> DoctorReport:
    """Run all prerequisite checks and return a :class:`DoctorReport`."""
    report = DoctorReport()

    for cmd, desc, hint, required, min_ver in _PREREQUISITES:
        try:
            path = shutil.which(cmd)
            # Try fallback command (pip3 -> pip, python3 -> python)
            fallback_cmd = cmd.rstrip("3")
            if not path and fallback_cmd != cmd:
                path = shutil.which(fallback_cmd)
                if path:
                    cmd = fallback_cmd

            if path:
                version = _get_version(cmd)
                if min_ver:
                    version_ok = _version_at_least(version, min_ver)
                else:
                    version_ok = True

                if not version_ok and min_ver and version is None:
                    check_hint = f"version unknown — cannot verify >={min_ver}"
                elif not version_ok:
                    check_hint = hint
                else:
                    check_hint = ""

                report.checks.append(
                    CheckResult(
                        name=cmd,
                        description=desc,
                        passed=version_ok,
                        version=version,
                        path=path,
                        required=required,
                        hint=check_hint,
                    )
                )
            else:
                report.checks.append(
                    CheckResult(
                        name=cmd,
                        description=desc,
                        passed=False,
                        required=required,
                        hint=hint,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            report.checks.append(
                CheckResult(
                    name=cmd,
                    description=desc,
                    passed=False,
                    required=required,
                    hint=f"check failed: {exc}",
                )
            )

    return report


def check_env_vars() -> list[CheckResult]:
    """Check key environment variables and return informational results.

    All env-var checks are informational (``required=False``) and do not
    affect the overall pass/fail status of a :class:`DoctorReport`.
    """
    return [
        CheckResult(
            name=var,
            description=desc,
            passed=bool(os.environ.get(var)),
            required=False,
        )
        for var, desc in _ENV_VARS
    ]


def format_report(report: DoctorReport, env_results: list[CheckResult]) -> str:
    """Format a doctor report as a human-readable checklist string.

    Returns a multi-line string with ``[✓]`` / ``[✗]`` / ``[-]`` markers.
    """
    lines: list[str] = ["StrawPot needs:"]

    for check in report.checks:
        if check.passed:
            detail = check.description
            if check.version:
                detail += f" ({check.version})"
            lines.append(f"  [✓] {detail}")
        else:
            # Failed checks: required get [✗], optional get [-]
            marker = "[✗]" if check.required else "[-]"
            detail = check.description
            if not check.required:
                detail += " (optional)"
            if check.version:
                detail += f" (found {check.version})"
            if check.hint:
                detail += f" — {check.hint}"
            lines.append(f"  {marker} {detail}")

    if env_results:
        lines.append("")
        lines.append("Environment:")
        for check in env_results:
            mark = "[✓]" if check.passed else "[-]"
            lines.append(f"  {mark} {check.name}")

    return "\n".join(lines)
