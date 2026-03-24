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


def test_report_ok_when_all_required_found():
    report = DoctorReport(
        checks=[
            CheckResult(name="python3", description="Python", found=True, required=True),
            CheckResult(name="gh", description="GitHub CLI", found=False, required=False),
        ]
    )
    assert report.ok is True


def test_report_not_ok_when_required_missing():
    report = DoctorReport(
        checks=[
            CheckResult(name="node", description="Node.js", found=False, required=True),
        ]
    )
    assert report.ok is False


def test_report_missing_required():
    report = DoctorReport(
        checks=[
            CheckResult(name="python3", description="Python", found=True, required=True),
            CheckResult(
                name="node", description="Node.js", found=False, required=True,
                hint="https://nodejs.org",
            ),
        ]
    )
    assert len(report.missing_required) == 1
    assert report.missing_required[0].name == "node"


def test_report_missing_optional():
    report = DoctorReport(
        checks=[
            CheckResult(name="gh", description="GitHub CLI", found=False, required=False),
            CheckResult(name="curl", description="curl", found=False, required=False),
        ]
    )
    assert len(report.missing_optional) == 2


# ---------------------------------------------------------------------------
# check_prerequisites
# ---------------------------------------------------------------------------


@patch("strawpot.doctor.subprocess.run")
@patch("strawpot.doctor.shutil.which")
def test_check_prerequisites_all_present(mock_which, mock_run):
    """All tools on PATH with valid versions => all found."""
    mock_which.return_value = "/usr/bin/fake"
    proc = MagicMock()
    proc.stdout = "v20.11.0"
    proc.stderr = ""
    mock_run.return_value = proc

    report = check_prerequisites()
    assert report.ok is True
    assert all(c.found for c in report.checks if c.required)


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
    assert any(not c.found for c in node_checks)


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
    assert python_check.found is False
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
    assert node_check.found is False
    assert node_check.version == "16.20.0"


# ---------------------------------------------------------------------------
# check_env_vars
# ---------------------------------------------------------------------------


def test_check_env_vars_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    results = check_env_vars()
    anthropic = next(r for r in results if r.name == "ANTHROPIC_API_KEY")
    assert anthropic.found is True


def test_check_env_vars_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    results = check_env_vars()
    anthropic = next(r for r in results if r.name == "ANTHROPIC_API_KEY")
    assert anthropic.found is False


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_pass_marker():
    report = DoctorReport(
        checks=[
            CheckResult(
                name="python3", description="Python 3.11+",
                found=True, version="3.12.1", required=True,
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
                found=False, required=True, hint="https://nodejs.org",
            ),
        ]
    )
    output = format_report(report, [])
    assert "[✗]" in output
    assert "nodejs.org" in output


def test_format_report_optional_marker():
    report = DoctorReport(
        checks=[
            CheckResult(
                name="gh", description="GitHub CLI",
                found=False, required=False, hint="https://cli.github.com",
            ),
        ]
    )
    output = format_report(report, [])
    assert "[-]" in output
    assert "optional" in output.lower()


def test_format_report_env_section():
    report = DoctorReport(checks=[])
    env = [
        CheckResult(name="ANTHROPIC_API_KEY", description="Anthropic API key", found=True),
        CheckResult(name="OPENAI_API_KEY", description="OpenAI API key", found=False),
    ]
    output = format_report(report, env)
    assert "Environment:" in output
    assert "ANTHROPIC_API_KEY" in output
    assert "OPENAI_API_KEY" in output
