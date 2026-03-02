"""Tests for strawpot.merge."""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from strawpot.merge import (
    MergeResult,
    _apply_patch,
    _apply_patch_all,
    _apply_patch_skip,
    _check_patch,
    _ensure_patch_available,
    _generate_patch,
    _prompt_conflict_resolution,
    merge_local,
    merge_pr,
    resolve_strategy,
)


# ---------------------------------------------------------------------------
# Helpers — real git repos for integration tests
# ---------------------------------------------------------------------------


def _init_repo(path):
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    readme = path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )


def _branches(path):
    """List local branch names."""
    result = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()


def _create_worktree(base_path, session_id):
    """Create a worktree + branch, return (worktree_path, branch)."""
    wt_path = str(base_path / "worktrees" / session_id)
    branch = f"strawpot/{session_id}"
    subprocess.run(
        ["git", "worktree", "add", wt_path, "-b", branch],
        cwd=str(base_path),
        capture_output=True,
        check=True,
    )
    return wt_path, branch


# ---------------------------------------------------------------------------
# resolve_strategy
# ---------------------------------------------------------------------------


class TestResolveStrategy:
    @patch("strawpot.merge._has_remote", return_value=True)
    def test_auto_with_remote_returns_pr(self, _mock):
        assert resolve_strategy("auto", "/fake") == "pr"

    @patch("strawpot.merge._has_remote", return_value=False)
    def test_auto_without_remote_returns_local(self, _mock):
        assert resolve_strategy("auto", "/fake") == "local"

    def test_local_passthrough(self):
        assert resolve_strategy("local", "/fake") == "local"

    def test_pr_passthrough(self):
        assert resolve_strategy("pr", "/fake") == "pr"


# ---------------------------------------------------------------------------
# _generate_patch
# ---------------------------------------------------------------------------


class TestGeneratePatch:
    def test_generates_diff(self, tmp_path):
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_patch")

        # Make a change on the worktree branch
        (tmp_path / "worktrees" / "run_patch" / "new_file.txt").write_text(
            "hello\n"
        )
        subprocess.run(
            ["git", "add", "new_file.txt"],
            cwd=wt_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add file"],
            cwd=wt_path,
            capture_output=True,
            check=True,
        )

        patch = _generate_patch("main", branch, cwd=wt_path)

        assert "new_file.txt" in patch
        assert "+hello" in patch

    def test_empty_diff(self, tmp_path):
        """No changes produces an empty patch."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_empty")

        patch = _generate_patch("main", branch, cwd=wt_path)

        assert patch.strip() == ""


# ---------------------------------------------------------------------------
# _check_patch
# ---------------------------------------------------------------------------


class TestCheckPatch:
    def test_empty_patch(self):
        assert _check_patch("", "/tmp") == []

    def test_clean_patch(self, tmp_path):
        """A patch that applies cleanly returns no conflicts."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_check")

        # Change on worktree branch
        (tmp_path / "worktrees" / "run_check" / "new.txt").write_text("x\n")
        subprocess.run(
            ["git", "add", "new.txt"], cwd=wt_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "add"], cwd=wt_path, capture_output=True
        )

        patch = _generate_patch("main", branch, cwd=wt_path)
        conflicts = _check_patch(patch, cwd=str(tmp_path))

        assert conflicts == []

    def test_conflicting_patch(self, tmp_path):
        """Working tree differs from patch context → conflict detected.

        git apply --check fails when the working tree has modifications
        that don't match the patch's expected ``-`` lines.
        """
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_conflict")

        # Modify README on worktree branch
        (tmp_path / "worktrees" / "run_conflict" / "README.md").write_text(
            "# Changed in worktree\n"
        )
        subprocess.run(
            ["git", "add", "README.md"], cwd=wt_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "wt change"],
            cwd=wt_path,
            capture_output=True,
        )

        # Commit a change on main, then make an uncommitted modification.
        # The patch's ``-`` lines reference the committed main content,
        # but the working tree has different content → conflict.
        (tmp_path / "README.md").write_text("# Committed on main\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "main change"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        # Uncommitted change in working tree
        (tmp_path / "README.md").write_text("# Uncommitted local edit\n")

        patch = _generate_patch("main", branch, cwd=wt_path)
        conflicts = _check_patch(patch, cwd=str(tmp_path))

        assert len(conflicts) > 0


# ---------------------------------------------------------------------------
# _prompt_conflict_resolution
# ---------------------------------------------------------------------------


class TestPromptConflictResolution:
    def test_displays_conflicts_and_returns_choice(self):
        lines = []
        echo = lines.append
        prompt = lambda *a, **kw: "a"

        choice = _prompt_conflict_resolution(
            ["src/auth.py", "src/config.py"], echo=echo, prompt=prompt
        )

        assert choice == "a"
        output = "\n".join(str(l) for l in lines)
        assert "src/auth.py" in output
        assert "src/config.py" in output
        assert "2 file(s)" in output

    def test_returns_discard(self):
        choice = _prompt_conflict_resolution(
            ["a.py"], echo=lambda x: None, prompt=lambda *a, **kw: "d"
        )
        assert choice == "d"

    def test_returns_skip(self):
        choice = _prompt_conflict_resolution(
            ["a.py"], echo=lambda x: None, prompt=lambda *a, **kw: "s"
        )
        assert choice == "s"


# ---------------------------------------------------------------------------
# merge_local
# ---------------------------------------------------------------------------


class TestMergeLocal:
    def test_no_changes(self, tmp_path):
        """Empty patch returns success with 'No changes' message."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_nochange")

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
        )

        assert result.success
        assert "No changes" in result.message
        assert result.strategy == "local"

    def test_clean_apply(self, tmp_path):
        """Patch with no conflicts is applied cleanly."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_clean")

        # Add new file on worktree branch
        (tmp_path / "worktrees" / "run_clean" / "feature.py").write_text(
            "print('hello')\n"
        )
        subprocess.run(
            ["git", "add", "feature.py"], cwd=wt_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "feature"],
            cwd=wt_path,
            capture_output=True,
        )

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
        )

        assert result.success
        assert "cleanly" in result.message
        # File should now exist in the base dir
        assert os.path.isfile(os.path.join(str(tmp_path), "feature.py"))

    def test_conflict_apply_all(self, tmp_path):
        """Conflicts with 'apply all' choice applies --3way."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_aa")

        # Modify README on worktree
        (tmp_path / "worktrees" / "run_aa" / "README.md").write_text(
            "# Worktree version\n"
        )
        subprocess.run(
            ["git", "add", "README.md"], cwd=wt_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "wt"], cwd=wt_path, capture_output=True
        )

        # Commit on main then leave uncommitted edit (creates conflict)
        (tmp_path / "README.md").write_text("# Committed on main\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "main"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "README.md").write_text("# Uncommitted local\n")

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
            echo=lambda x: None,
            prompt=lambda *a, **kw: "a",
        )

        assert result.strategy == "local"
        assert "override" in result.message.lower() or "applied" in result.message.lower()

    def test_conflict_discard(self, tmp_path):
        """Conflicts with 'discard' choice leaves base_dir unchanged."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_discard")

        # Modify README on worktree
        (tmp_path / "worktrees" / "run_discard" / "README.md").write_text(
            "# Worktree\n"
        )
        subprocess.run(
            ["git", "add", "README.md"], cwd=wt_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "wt"], cwd=wt_path, capture_output=True
        )

        # Commit on main then leave uncommitted edit (creates conflict)
        (tmp_path / "README.md").write_text("# Committed\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "main"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        local_edit = "# Local uncommitted\n"
        (tmp_path / "README.md").write_text(local_edit)

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
            echo=lambda x: None,
            prompt=lambda *a, **kw: "d",
        )

        assert result.success
        assert "discard" in result.message.lower()
        # README should still be the local uncommitted version
        assert (tmp_path / "README.md").read_text() == local_edit

    def test_conflict_skip(self, tmp_path):
        """Conflicts with 'skip' choice applies non-conflicting changes."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_skip")

        # Add a new file AND modify README on worktree
        (tmp_path / "worktrees" / "run_skip" / "new.txt").write_text("new\n")
        (tmp_path / "worktrees" / "run_skip" / "README.md").write_text(
            "# Worktree\n"
        )
        subprocess.run(
            ["git", "add", "-A"], cwd=wt_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "wt"], cwd=wt_path, capture_output=True
        )

        # Commit on main then leave uncommitted edit (creates conflict)
        (tmp_path / "README.md").write_text("# Committed on main\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "main"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "README.md").write_text("# Uncommitted local\n")

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
            echo=lambda x: None,
            prompt=lambda *a, **kw: "s",
        )

        assert result.success
        assert "skip" in result.message.lower()


# ---------------------------------------------------------------------------
# merge_pr
# ---------------------------------------------------------------------------


class TestMergePR:
    @patch("strawpot.merge._git")
    @patch("strawpot.merge.subprocess.run")
    def test_push_and_create_pr(self, mock_run, mock_git):
        """Successful push + PR creation."""
        # status --porcelain: no uncommitted changes
        mock_git.side_effect = [
            MagicMock(stdout="", returncode=0),  # status
            MagicMock(returncode=0, stderr=""),  # push
        ]
        # pr_command
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/pr/1\n", stderr=""
        )

        result = merge_pr(
            base_branch="main",
            session_branch="strawpot/run_abc",
            worktree_dir="/fake/wt",
            base_dir="/fake/base",
            pr_command="gh pr create --base {base_branch} --head {session_branch}",
            echo=lambda x: None,
        )

        assert result.success
        assert result.pr_url == "https://github.com/pr/1"
        assert result.strategy == "pr"

        # PR command should be tokenized via shlex (no shell=True)
        mock_run.assert_called_once()
        call_args, call_kwargs = mock_run.call_args
        assert call_args[0] == [
            "gh", "pr", "create",
            "--base", "main",
            "--head", "strawpot/run_abc",
        ]
        assert "shell" not in call_kwargs

    @patch("strawpot.merge._git")
    def test_push_fails(self, mock_git):
        """Push failure returns error."""
        mock_git.side_effect = [
            MagicMock(stdout="", returncode=0),  # status
            MagicMock(returncode=1, stderr="permission denied"),  # push
        ]

        result = merge_pr(
            base_branch="main",
            session_branch="strawpot/run_fail",
            worktree_dir="/fake/wt",
            base_dir="/fake/base",
            pr_command="gh pr create",
            echo=lambda x: None,
        )

        assert not result.success
        assert "permission denied" in result.message

    @patch("strawpot.merge._git")
    @patch("strawpot.merge.subprocess.run")
    def test_push_ok_pr_fails(self, mock_run, mock_git):
        """Push succeeds but PR creation fails — partial success."""
        mock_git.side_effect = [
            MagicMock(stdout="", returncode=0),  # status
            MagicMock(returncode=0, stderr=""),  # push
        ]
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="gh: not found"
        )

        result = merge_pr(
            base_branch="main",
            session_branch="strawpot/run_partial",
            worktree_dir="/fake/wt",
            base_dir="/fake/base",
            pr_command="gh pr create",
            echo=lambda x: None,
        )

        assert result.success  # branch pushed
        assert result.pr_url is None
        assert "PR creation failed" in result.message

    @patch("strawpot.merge._git")
    @patch("strawpot.merge.subprocess.run")
    def test_commits_uncommitted_changes(self, mock_run, mock_git):
        """Uncommitted changes are committed before push."""
        mock_git.side_effect = [
            MagicMock(stdout="M file.py\n", returncode=0),  # status (dirty)
            MagicMock(returncode=0),  # add -A
            MagicMock(returncode=0),  # commit
            MagicMock(returncode=0, stderr=""),  # push
        ]
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://pr/1\n", stderr=""
        )

        merge_pr(
            base_branch="main",
            session_branch="strawpot/run_dirty",
            worktree_dir="/fake/wt",
            base_dir="/fake/base",
            pr_command="gh pr create",
            echo=lambda x: None,
        )

        # Check add -A and commit were called
        calls = mock_git.call_args_list
        assert calls[1][0][0] == ["add", "-A"]
        assert calls[2][0][0][0] == "commit"

    @patch("strawpot.merge._git")
    def test_empty_pr_command(self, mock_git):
        """Empty pr_command skips PR creation."""
        mock_git.side_effect = [
            MagicMock(stdout="", returncode=0),  # status
            MagicMock(returncode=0, stderr=""),  # push
        ]

        result = merge_pr(
            base_branch="main",
            session_branch="strawpot/run_noPR",
            worktree_dir="/fake/wt",
            base_dir="/fake/base",
            pr_command="",
            echo=lambda x: None,
        )

        assert result.success
        assert result.pr_url is None

    @patch("strawpot.merge._git")
    @patch("strawpot.merge.subprocess.run")
    def test_pr_command_shlex_tokenization(self, mock_run, mock_git):
        """Complex pr_command with quoted args is tokenized correctly."""
        mock_git.side_effect = [
            MagicMock(stdout="", returncode=0),  # status
            MagicMock(returncode=0, stderr=""),  # push
        ]
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://pr/2\n", stderr=""
        )

        merge_pr(
            base_branch="main",
            session_branch="strawpot/run_x",
            worktree_dir="/fake/wt",
            base_dir="/fake/base",
            pr_command='my-tool --title "PR for {session_branch}" --base {base_branch}',
            echo=lambda x: None,
        )

        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "my-tool",
            "--title", "PR for strawpot/run_x",
            "--base", "main",
        ]



# ---------------------------------------------------------------------------
# _ensure_patch_available
# ---------------------------------------------------------------------------


class TestEnsurePatchAvailable:
    @patch("strawpot.merge.shutil.which", return_value="/usr/bin/patch")
    def test_patch_found(self, _mock):
        """No error when patch is on PATH."""
        _ensure_patch_available()  # should not raise

    @patch("strawpot.merge.shutil.which", return_value=None)
    def test_patch_not_found(self, _mock):
        """RuntimeError when patch is missing."""
        with pytest.raises(RuntimeError, match="patch.*required"):
            _ensure_patch_available()

    @patch("strawpot.merge._is_git_repo", return_value=False)
    @patch("strawpot.merge.shutil.which", return_value=None)
    @patch("strawpot.merge._generate_patch", return_value="diff content\n")
    def test_merge_local_checks_patch(self, _mock_gen, _mock_which, _mock_git):
        """merge_local raises RuntimeError for non-git dir when patch is missing."""
        with pytest.raises(RuntimeError, match="patch.*required"):
            merge_local(
                base_branch="main",
                session_branch="strawpot/run_x",
                worktree_dir="/fake/wt",
                base_dir="/fake/base",
            )
