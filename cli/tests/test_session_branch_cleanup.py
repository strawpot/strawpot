"""Tests for session branch cleanup after teardown.

Covers the ``_cleanup_session_branch`` logic added for issue #459:
auto-cleanup of ``strawpot/run_*`` branches when a session tears down.
"""

from unittest.mock import MagicMock, patch

from strawpot.config import StrawPotConfig
from strawpot.isolation.protocol import IsolatedEnv
from strawpot.session import MergeOutcome, Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    overrides.setdefault("memory", "")
    return StrawPotConfig(**overrides)


def _make_session(
    *,
    config=None,
    keep_branch=False,
    interrupted=False,
    env=None,
    working_dir="/tmp/fake",
):
    """Build a minimal Session wired for branch-cleanup testing."""
    config = config or _make_config()
    isolator = MagicMock()
    wrapper = MagicMock()
    runtime = MagicMock()

    session = Session(
        config=config,
        wrapper=wrapper,
        runtime=runtime,
        isolator=isolator,
        resolve_role=MagicMock(),
        resolve_role_dirs=MagicMock(),
        keep_branch=keep_branch,
    )
    session._env = env or IsolatedEnv(path="/tmp/wt", branch="strawpot/run_abc123")
    session._working_dir = working_dir
    session._interrupted = interrupted
    return session


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_defaults():
    """cleanup_branches and cleanup_remote default to True."""
    config = StrawPotConfig()
    assert config.cleanup_branches is True
    assert config.cleanup_remote is True


def test_config_from_toml(tmp_path):
    """Config values are loaded from the [session] TOML table."""
    from strawpot.config import load_config

    toml_file = tmp_path / "strawpot.toml"
    toml_file.write_text(
        "[session]\n"
        "cleanup_branches = false\n"
        "cleanup_remote = false\n"
    )
    config = load_config(tmp_path)
    assert config.cleanup_branches is False
    assert config.cleanup_remote is False


# ---------------------------------------------------------------------------
# Happy path — successful session deletes branch
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_remote_branch")
@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_branch_checked_out_elsewhere", return_value=False)
@patch.object(Session, "_branch_has_open_pr", return_value=False)
def test_cleanup_deletes_branch_on_success(
    mock_pr, mock_checkout, mock_local, mock_remote
):
    session = _make_session()
    session._cleanup_session_branch(merge_outcome=MergeOutcome.MERGED)

    mock_local.assert_called_once_with(
        "strawpot/run_abc123", "/tmp/fake"
    )
    mock_remote.assert_called_once_with(
        "strawpot/run_abc123", "/tmp/fake"
    )


# ---------------------------------------------------------------------------
# Edge case: --keep-branch flag
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_delete_remote_branch")
def test_keep_branch_flag_skips_cleanup(mock_remote, mock_local):
    session = _make_session(keep_branch=True)
    session._cleanup_session_branch(merge_outcome=MergeOutcome.MERGED)

    mock_local.assert_not_called()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: cleanup_branches=false in config
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_delete_remote_branch")
def test_config_cleanup_branches_false(mock_remote, mock_local):
    config = _make_config(cleanup_branches=False)
    session = _make_session(config=config)
    session._cleanup_session_branch(merge_outcome=MergeOutcome.MERGED)

    mock_local.assert_not_called()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: cleanup_remote=false keeps remote but deletes local
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_remote_branch")
@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_branch_checked_out_elsewhere", return_value=False)
@patch.object(Session, "_branch_has_open_pr", return_value=False)
def test_config_cleanup_remote_false(
    mock_pr, mock_checkout, mock_local, mock_remote
):
    config = _make_config(cleanup_remote=False)
    session = _make_session(config=config)
    session._cleanup_session_branch(merge_outcome=MergeOutcome.MERGED)

    mock_local.assert_called_once()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: interrupted session (force-stopped)
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_delete_remote_branch")
def test_interrupted_session_keeps_branch(mock_remote, mock_local):
    session = _make_session(interrupted=True)
    session._cleanup_session_branch(merge_outcome=MergeOutcome.MERGED)

    mock_local.assert_not_called()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: merge failed / unmerged changes
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_delete_remote_branch")
def test_merge_failed_keeps_branch(mock_remote, mock_local):
    session = _make_session()
    session._cleanup_session_branch(merge_outcome=MergeOutcome.FAILED)

    mock_local.assert_not_called()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: branch has open PR
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_delete_remote_branch")
@patch.object(Session, "_branch_has_open_pr", return_value=True)
@patch.object(Session, "_branch_checked_out_elsewhere", return_value=False)
def test_open_pr_keeps_branch(mock_checkout, mock_pr, mock_remote, mock_local):
    session = _make_session()
    session._cleanup_session_branch(merge_outcome=MergeOutcome.MERGED)

    mock_local.assert_not_called()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: branch checked out elsewhere
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_delete_remote_branch")
@patch.object(Session, "_branch_checked_out_elsewhere", return_value=True)
@patch.object(Session, "_branch_has_open_pr", return_value=False)
def test_checked_out_elsewhere_keeps_branch(
    mock_pr, mock_checkout, mock_remote, mock_local
):
    session = _make_session()
    session._cleanup_session_branch(merge_outcome=MergeOutcome.MERGED)

    mock_local.assert_not_called()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# _branch_has_open_pr helper
# ---------------------------------------------------------------------------


def test_branch_has_open_pr_no_gh(monkeypatch):
    """When gh is not installed, returns False (safe default)."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert Session._branch_has_open_pr("strawpot/run_x", "/tmp") is False


@patch("subprocess.run")
def test_branch_has_open_pr_true(mock_run, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
    mock_run.return_value = MagicMock(
        returncode=0, stdout='[{"number": 42}]'
    )
    assert Session._branch_has_open_pr("strawpot/run_x", "/tmp") is True


@patch("subprocess.run")
def test_branch_has_open_pr_false(mock_run, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
    mock_run.return_value = MagicMock(returncode=0, stdout="[]")
    assert Session._branch_has_open_pr("strawpot/run_x", "/tmp") is False


@patch("subprocess.run")
def test_branch_has_open_pr_gh_failure_assumes_open(mock_run, monkeypatch):
    """When gh exits non-zero, assume an open PR exists (safe default)."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    assert Session._branch_has_open_pr("strawpot/run_x", "/tmp") is True


@patch("subprocess.run")
def test_branch_has_open_pr_timeout_assumes_open(mock_run, monkeypatch):
    """When gh times out, assume an open PR exists (safe default)."""
    import subprocess as sp

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
    mock_run.side_effect = sp.TimeoutExpired(cmd="gh", timeout=15)
    assert Session._branch_has_open_pr("strawpot/run_x", "/tmp") is True


# ---------------------------------------------------------------------------
# _branch_checked_out_elsewhere helper
# ---------------------------------------------------------------------------


@patch("strawpot.session._git")
def test_branch_checked_out_elsewhere_true(mock_git):
    mock_git.return_value = MagicMock(
        returncode=0,
        stdout=(
            "worktree /home/user/project\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /tmp/wt2\n"
            "HEAD def456\n"
            "branch refs/heads/strawpot/run_abc123\n"
        ),
    )
    assert (
        Session._branch_checked_out_elsewhere(
            "strawpot/run_abc123", "/home/user/project"
        )
        is True
    )


@patch("strawpot.session._git")
def test_branch_checked_out_elsewhere_git_failure_assumes_true(mock_git):
    """When git worktree list fails, assume checked out (safe default)."""
    mock_git.return_value = MagicMock(returncode=128, stdout="")
    assert (
        Session._branch_checked_out_elsewhere(
            "strawpot/run_abc123", "/home/user/project"
        )
        is True
    )


@patch("strawpot.session._git")
def test_branch_checked_out_elsewhere_false(mock_git):
    mock_git.return_value = MagicMock(
        returncode=0,
        stdout=(
            "worktree /home/user/project\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
        ),
    )
    assert (
        Session._branch_checked_out_elsewhere(
            "strawpot/run_abc123", "/home/user/project"
        )
        is False
    )


# ---------------------------------------------------------------------------
# _delete_local_branch helper
# ---------------------------------------------------------------------------


@patch("strawpot.session._git")
def test_delete_local_branch_success(mock_git):
    mock_git.return_value = MagicMock(returncode=0, stderr="")
    Session._delete_local_branch("strawpot/run_x", "/tmp")
    mock_git.assert_called_once_with(
        ["branch", "-D", "strawpot/run_x"], cwd="/tmp"
    )


@patch("strawpot.session._git")
def test_delete_local_branch_failure_does_not_raise(mock_git):
    mock_git.return_value = MagicMock(returncode=1, stderr="error")
    # Should not raise — just logs a warning
    Session._delete_local_branch("strawpot/run_x", "/tmp")


# ---------------------------------------------------------------------------
# _delete_remote_branch helper
# ---------------------------------------------------------------------------


@patch("strawpot.session._git")
def test_delete_remote_branch_not_on_remote(mock_git):
    """If branch doesn't exist on remote, skip deletion."""
    mock_git.return_value = MagicMock(returncode=0, stdout="")
    Session._delete_remote_branch("strawpot/run_x", "/tmp")
    # Only ls-remote called, not push --delete
    assert mock_git.call_count == 1
    assert mock_git.call_args[0][0][:2] == ["ls-remote", "--heads"]


@patch("strawpot.session._git")
def test_delete_remote_branch_success(mock_git):
    """If branch exists on remote, delete it."""
    mock_git.side_effect = [
        MagicMock(returncode=0, stdout="abc123\trefs/heads/strawpot/run_x"),
        MagicMock(returncode=0, stderr=""),
    ]
    Session._delete_remote_branch("strawpot/run_x", "/tmp")
    assert mock_git.call_count == 2
    assert mock_git.call_args_list[1][0][0] == [
        "push", "origin", "--delete", "strawpot/run_x"
    ]


# ---------------------------------------------------------------------------
# Integration: stop() invokes branch cleanup
# ---------------------------------------------------------------------------


@patch.object(Session, "_archive_session_dir")
@patch.object(Session, "_cleanup_session_branch")
@patch.object(Session, "_merge_session_changes", return_value=MergeOutcome.MERGED)
@patch.object(Session, "_stop_denden_server")
def test_stop_calls_cleanup_session_branch(
    mock_denden, mock_merge, mock_cleanup, mock_archive
):
    session = _make_session()
    # Simulate having agents dict but no live agents
    session._agents = {}

    session.stop()

    mock_cleanup.assert_called_once_with(merge_outcome=MergeOutcome.MERGED)


@patch.object(Session, "_archive_session_dir")
@patch.object(Session, "_cleanup_session_branch")
@patch.object(Session, "_merge_session_changes", side_effect=Exception("boom"))
@patch.object(Session, "_stop_denden_server")
def test_stop_passes_merge_failure_to_cleanup(
    mock_denden, mock_merge, mock_cleanup, mock_archive
):
    session = _make_session()
    session._agents = {}

    session.stop()

    mock_cleanup.assert_called_once_with(merge_outcome=MergeOutcome.FAILED)


@patch.object(Session, "_archive_session_dir")
@patch.object(Session, "_cleanup_session_branch")
@patch.object(Session, "_merge_session_changes", return_value=MergeOutcome.KEPT_FOR_PR)
@patch.object(Session, "_stop_denden_server")
def test_stop_passes_kept_for_pr_to_cleanup(
    mock_denden, mock_merge, mock_cleanup, mock_archive
):
    session = _make_session()
    session._agents = {}

    session.stop()

    mock_cleanup.assert_called_once_with(merge_outcome=MergeOutcome.KEPT_FOR_PR)


# ---------------------------------------------------------------------------
# Edge case: KEPT_FOR_PR — deletes local, keeps remote
# ---------------------------------------------------------------------------


@patch.object(Session, "_delete_remote_branch")
@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_branch_checked_out_elsewhere", return_value=False)
def test_kept_for_pr_deletes_local_keeps_remote(
    mock_checkout, mock_local, mock_remote
):
    """When merge outcome is KEPT_FOR_PR, local branch is deleted but remote is preserved."""
    session = _make_session()
    session._cleanup_session_branch(merge_outcome=MergeOutcome.KEPT_FOR_PR)

    mock_local.assert_called_once_with("strawpot/run_abc123", "/tmp/fake")
    mock_remote.assert_not_called()


@patch.object(Session, "_delete_remote_branch")
@patch.object(Session, "_delete_local_branch")
@patch.object(Session, "_branch_checked_out_elsewhere", return_value=True)
def test_kept_for_pr_checked_out_elsewhere_skips_all(
    mock_checkout, mock_local, mock_remote
):
    """KEPT_FOR_PR still respects checked-out-elsewhere guard."""
    session = _make_session()
    session._cleanup_session_branch(merge_outcome=MergeOutcome.KEPT_FOR_PR)

    mock_local.assert_not_called()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# MergeOutcome enum
# ---------------------------------------------------------------------------


def test_merge_outcome_values():
    """MergeOutcome has exactly the three expected members."""
    assert set(MergeOutcome) == {
        MergeOutcome.MERGED,
        MergeOutcome.KEPT_FOR_PR,
        MergeOutcome.FAILED,
    }


def test_merge_outcome_identity():
    """Enum members compare by identity, not by value."""
    assert MergeOutcome.MERGED is not MergeOutcome.FAILED
    assert MergeOutcome.KEPT_FOR_PR is not MergeOutcome.MERGED
