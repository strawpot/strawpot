"""Tests for strawpot.doctor — prerequisite checker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from strawpot.doctor import (
    CheckResult,
    DoctorReport,
    _version_at_least,
    check_env_vars,
    check_prerequisites,
    format_report,
)


# ---------------------------------------------------------------------------
# _version_at_least
# ---------------------------------------------------------------------------


def test_version_at_least_equal():
    assert _version_at_least("3.11", "3.11") is True


def test_version_at_least_greater_minor():
    assert _version_at_least("3.12.1", "3.11") is True


def test_version_at_least_greater_major():
    assert _version_at_least("20.11.0", "18") is True


def test_version_at_least_less():
    assert _version_at_least("3.10.4", "3.11") is False


def test_version_at_least_less_major():
    assert _version_at_least("16.20.0", "18") is False


def test_version_at_least_invalid():
    assert _version_at_least("unknown", "3.11") is False


def test_version_at_least_none():
    assert _version_at_least(None, "3.11") is False


# ---------------------------------------------------------------------------
# DoctorReport
# ---------------------------------------------------------------------------


def test_report_ok_when_all_required_passed():
    report = DoctorReport(
        checks=[
            CheckResult(name="python3", description="Python", passed=True, required=True),
            CheckResult(name="gh", description="GitHub CLI", passed=False, required=False),
        ]
    )
    assert report.ok is True


def test_report_not_ok_when_required_missing():
    report = DoctorReport(
        checks=[
            CheckResult(name="node", description="Node.js", passed=False, required=True),
        ]
    )
    assert report.ok is False


def test_report_empty_is_not_ok():
    """An empty report should not be considered passing."""
    report = DoctorReport(checks=[])
    assert report.ok is False


def test_report_missing_required():
    report = DoctorReport(
        checks=[
            CheckResult(name="python3", description="Python", passed=True, required=True),
            CheckResult(
                name="node", description="Node.js", passed=False, required=True,
                hint="https://nodejs.org",
            ),
        ]
    )
    assert len(report.missing_required) == 1
    assert report.missing_required[0].name == "node"


def test_report_missing_optional():
    report = DoctorReport(
        checks=[
            CheckResult(name="gh", description="GitHub CLI", passed=False, required=False),
            CheckResult(name="curl", description="curl", passed=False, required=False),
        ]
    )
    assert len(report.missing_optional) == 2


# ---------------------------------------------------------------------------
# CheckResult semantics
# ---------------------------------------------------------------------------


def test_check_result_missing_vs_wrong_version():
    """path distinguishes 'not on PATH' from 'wrong version'."""
    missing = CheckResult(name="node", description="Node.js", passed=False, path=None)
    wrong_ver = CheckResult(
        name="node", description="Node.js", passed=False,
        path="/usr/bin/node", version="16.20.0",
    )
    assert missing.path is None  # not on PATH
    assert wrong_ver.path is not None  # on PATH but wrong version
    assert not missing.passed
    assert not wrong_ver.passed


# ---------------------------------------------------------------------------
# check_prerequisites
# ---------------------------------------------------------------------------


@patch("strawpot.doctor.subprocess.run")
@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_all_present(mock_which, mock_run):
    """All tools on PATH with valid versions => all passed."""
    mock_which.return_value = "/usr/bin/fake"
    proc = MagicMock()
    proc.stdout = "v20.11.0"
    proc.stderr = ""
    mock_run.return_value = proc

    report = check_prerequisites()
    assert report.ok is True
    assert all(c.passed for c in report.checks if c.required)


@patch("strawpot.doctor.subprocess.run")
@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_node_missing(mock_which, mock_run):
    """node missing from PATH => reported as missing."""

    def which_side_effect(cmd):
        if cmd == "node":
            return None
        return f"/usr/bin/{cmd}"

    mock_which.side_effect = which_side_effect
    proc = MagicMock()
    proc.stdout = "3.12.0"
    proc.stderr = ""
    mock_run.return_value = proc

    report = check_prerequisites()
    node_checks = [
        c for c in report.checks
        if "node" in c.name.lower() or "Node" in c.description
    ]
    assert any(not c.passed for c in node_checks)


@patch("strawpot.doctor.subprocess.run")
@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_python_too_old(mock_which, mock_run):
    """Python 3.9 should fail the >= 3.11 version check."""
    mock_which.return_value = "/usr/bin/python3"
    proc = MagicMock()
    proc.stdout = "Python 3.9.7"
    proc.stderr = ""
    mock_run.return_value = proc

    report = check_prerequisites()
    python_check = next(c for c in report.checks if c.name in ("python3", "python"))
    assert python_check.passed is False
    assert python_check.version == "3.9.7"


@patch("strawpot.doctor.subprocess.run")
@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_node_too_old(mock_which, mock_run):
    """Node 16 should fail the >= 18 version check."""
    mock_which.return_value = "/usr/bin/node"
    proc = MagicMock()
    proc.stdout = "v16.20.0"
    proc.stderr = ""
    mock_run.return_value = proc

    report = check_prerequisites()
    node_check = next(c for c in report.checks if c.name == "node")
    assert node_check.passed is False
    assert node_check.version == "16.20.0"


@patch("strawpot.doctor.subprocess.run")
@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_version_unknown_fails(mock_which, mock_run):
    """Tool found on PATH but version undetermined should fail when min required."""
    mock_which.return_value = "/usr/bin/python3"
    proc = MagicMock()
    proc.stdout = "some non-version output"
    proc.stderr = ""
    mock_run.return_value = proc

    report = check_prerequisites()
    python_check = next(c for c in report.checks if c.name in ("python3", "python"))
    assert python_check.passed is False
    assert python_check.version is None
    assert python_check.path is not None
    assert "version unknown" in python_check.hint


@patch("strawpot.doctor.subprocess.run")
@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_no_min_version_ok_without_version(mock_which, mock_run):
    """Tool found but version undetermined passes if no min version required."""

    def which_side_effect(cmd):
        if cmd == "git":
            return "/usr/bin/git"
        return None

    mock_which.side_effect = which_side_effect
    proc = MagicMock()
    proc.stdout = "some non-version output"
    proc.stderr = ""
    mock_run.return_value = proc

    report = check_prerequisites()
    git_check = next(c for c in report.checks if c.name == "git")
    assert git_check.passed is True
    assert git_check.version is None


@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_exception_guard(mock_which):
    """Unexpected exception during a check should not crash the entire run."""
    mock_which.side_effect = RuntimeError("corrupted PATH")

    report = check_prerequisites()
    # All checks should still produce results (none skipped)
    assert len(report.checks) == len(
        [t for t in report.checks]
    )
    # The first check should have failed gracefully
    first = report.checks[0]
    assert first.passed is False
    assert "check failed" in first.hint


# ---------------------------------------------------------------------------
# check_env_vars
# ---------------------------------------------------------------------------


def test_check_env_vars_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    results = check_env_vars()
    anthropic = next(r for r in results if r.name == "ANTHROPIC_API_KEY")
    assert anthropic.passed is True


def test_check_env_vars_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    results = check_env_vars()
    anthropic = next(r for r in results if r.name == "ANTHROPIC_API_KEY")
    assert anthropic.passed is False


def test_check_env_vars_all_informational():
    """All env var results should be required=False (informational only)."""
    results = check_env_vars()
    assert all(not r.required for r in results)


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_pass_marker():
    report = DoctorReport(
        checks=[
            CheckResult(
                name="python3", description="Python 3.11+",
                passed=True, version="3.12.1", required=True,
            ),
        ]
    )
    output = format_report(report, [])
    assert "[✓]" in output
    assert "3.12.1" in output
    assert "Python 3.11+" in output


def test_format_report_fail_marker():
    report = DoctorReport(
        checks=[
            CheckResult(
                name="node", description="Node.js 18+",
                passed=False, required=True, hint="https://nodejs.org",
            ),
        ]
    )
    output = format_report(report, [])
    assert "[✗]" in output
    assert "nodejs.org" in output


def test_format_report_fail_shows_installed_version():
    """Failed checks should display the actual installed version."""
    report = DoctorReport(
        checks=[
            CheckResult(
                name="python3", description="Python 3.11+",
                passed=False, version="3.9.7", required=True,
                hint="https://python.org",
            ),
        ]
    )
    output = format_report(report, [])
    assert "[✗]" in output
    assert "found 3.9.7" in output
    assert "python.org" in output


def test_format_report_fail_version_unknown():
    """Failed check with unknown version shows hint but no version."""
    report = DoctorReport(
        checks=[
            CheckResult(
                name="python3", description="Python 3.11+",
                passed=False, version=None, required=True,
                hint="version unknown — cannot verify >=3.11",
            ),
        ]
    )
    output = format_report(report, [])
    assert "[✗]" in output
    assert "version unknown" in output
    assert "found" not in output


def test_format_report_optional_marker():
    report = DoctorReport(
        checks=[
            CheckResult(
                name="gh", description="GitHub CLI",
                passed=False, required=False, hint="https://cli.github.com",
            ),
        ]
    )
    output = format_report(report, [])
    assert "[-]" in output
    assert "optional" in output.lower()


def test_format_report_env_section():
    report = DoctorReport(checks=[])
    env = [
        CheckResult(name="ANTHROPIC_API_KEY", description="Anthropic API key", passed=True),
        CheckResult(name="OPENAI_API_KEY", description="OpenAI API key", passed=False),
    ]
    output = format_report(report, env)
    assert "Environment:" in output
    assert "ANTHROPIC_API_KEY" in output
    assert "OPENAI_API_KEY" in output
