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
    detect_pr_created,
    merge_local,
    save_patch_file,
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
# detect_pr_created
# ---------------------------------------------------------------------------


class TestDetectPrCreated:
    @patch("strawpot.merge.shutil.which", return_value=None)
    def test_no_gh_returns_false(self, _mock):
        assert detect_pr_created("strawpot/run_x", "/fake") is False

    @patch("strawpot.merge.shutil.which", return_value="/usr/bin/gh")
    @patch("strawpot.merge.subprocess.run")
    def test_pr_exists(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='[{"number":42}]', stderr=""
        )
        assert detect_pr_created("strawpot/run_x", "/fake") is True

    @patch("strawpot.merge.shutil.which", return_value="/usr/bin/gh")
    @patch("strawpot.merge.subprocess.run")
    def test_no_pr(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )
        assert detect_pr_created("strawpot/run_x", "/fake") is False

    @patch("strawpot.merge.shutil.which", return_value="/usr/bin/gh")
    @patch("strawpot.merge.subprocess.run")
    def test_gh_fails_returns_false(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        assert detect_pr_created("strawpot/run_x", "/fake") is False

    @patch("strawpot.merge.shutil.which", return_value="/usr/bin/gh")
    @patch("strawpot.merge.subprocess.run", side_effect=Exception("timeout"))
    def test_exception_returns_false(self, _mock_run, _mock_which):
        assert detect_pr_created("strawpot/run_x", "/fake") is False


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
        """Working tree differs from patch context — conflict detected.

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
        assert result.success

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

        # --3way may fail on some git versions; verify the code path runs
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


# ---------------------------------------------------------------------------
# save_patch_file
# ---------------------------------------------------------------------------


class TestSavePatchFile:
    def test_creates_dir_and_file(self, tmp_path):
        """Creates the patches directory and writes the .patch file."""
        patch_dir = str(tmp_path / "patches")
        patch_content = "diff --git a/foo.py b/foo.py\n+hello\n"

        path = save_patch_file(patch_content, patch_dir, "run_abc")

        assert os.path.isdir(patch_dir)
        assert os.path.isfile(path)
        assert path.endswith("run_abc.patch")
        with open(path) as f:
            assert f.read() == patch_content

    def test_existing_dir(self, tmp_path):
        """Works when the directory already exists."""
        patch_dir = str(tmp_path / "patches")
        os.makedirs(patch_dir)

        path = save_patch_file("diff\n", patch_dir, "run_xyz")
        assert os.path.isfile(path)

    def test_overwrites_existing_file(self, tmp_path):
        """Overwrites an existing patch for the same session."""
        patch_dir = str(tmp_path / "patches")
        save_patch_file("old\n", patch_dir, "run_1")
        path = save_patch_file("new\n", patch_dir, "run_1")

        with open(path) as f:
            assert f.read() == "new\n"


# ---------------------------------------------------------------------------
# merge_local — headless conflict (patch-file preservation)
# ---------------------------------------------------------------------------


class TestMergeLocalHeadlessConflict:
    def test_conflict_saves_patch_file(self, tmp_path):
        """Headless mode saves a .patch file on conflict instead of discarding."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_headless")

        # Modify README on worktree branch
        (tmp_path / "worktrees" / "run_headless" / "README.md").write_text(
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

        patch_dir = str(tmp_path / ".strawpot" / "patches")

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
            patch_save_dir=patch_dir,
            session_id="run_headless",
        )

        assert not result.success
        assert "Patch saved" in result.message
        assert "run_headless" in result.message

        # Verify patch file was written and contains the diff
        patch_path = os.path.join(patch_dir, "run_headless.patch")
        assert os.path.isfile(patch_path)
        with open(patch_path) as f:
            patch_content = f.read()
        assert "README.md" in patch_content

    def test_clean_merge_ignores_patch_save(self, tmp_path):
        """When merge is clean, patch_save_dir is not used."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_clean_hl")

        # Add a new file (no conflict)
        (tmp_path / "worktrees" / "run_clean_hl" / "new.txt").write_text("x\n")
        subprocess.run(
            ["git", "add", "new.txt"], cwd=wt_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "add"], cwd=wt_path, capture_output=True
        )

        patch_dir = str(tmp_path / ".strawpot" / "patches")

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
            patch_save_dir=patch_dir,
            session_id="run_clean_hl",
        )

        assert result.success
        assert "cleanly" in result.message
        # No patch file should exist
        assert not os.path.exists(patch_dir)

    def test_no_changes_ignores_patch_save(self, tmp_path):
        """Empty diff with patch_save_dir still returns 'No changes'."""
        _init_repo(tmp_path)
        wt_path, branch = _create_worktree(tmp_path, "run_empty_hl")

        result = merge_local(
            base_branch="main",
            session_branch=branch,
            worktree_dir=wt_path,
            base_dir=str(tmp_path),
            patch_save_dir=str(tmp_path / ".strawpot" / "patches"),
            session_id="run_empty_hl",
        )

        assert result.success
        assert "No changes" in result.message
