"""WorktreeIsolator — git-worktree-based session isolation.

Creates one git worktree per session so agents work on an isolated branch.
Multiple concurrent sessions are safe — each gets its own branch under
the ``strawpot/`` namespace.

Worktrees are stored outside the project tree under ``STRAWPOT_HOME``
to avoid interfering with IDEs, file watchers, and gitignore:

    <STRAWPOT_HOME>/worktrees/<project_hash>/<session_id>

Merge strategy and conflict resolution are handled by the session layer,
not here.  This module only manages worktree creation and removal.
"""

import hashlib
import os
import subprocess

from strawpot.config import get_strawpot_home
from strawpot.isolation.protocol import IsolatedEnv


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _is_git_repo(path: str) -> bool:
    """Check whether *path* is inside a git repository."""
    result = _git(["rev-parse", "--git-dir"], cwd=path)
    return result.returncode == 0


def _project_hash(base_dir: str) -> str:
    """Return a short hash of the absolute project path."""
    abs_path = os.path.abspath(base_dir)
    return hashlib.sha256(abs_path.encode()).hexdigest()[:12]


class WorktreeIsolator:
    """Implements Isolator using git worktrees.

    Each session gets a worktree at
    ``<STRAWPOT_HOME>/worktrees/<project_hash>/<session_id>``
    on a new branch ``strawpot/<session_id>``.
    """

    def create(self, *, session_id: str, base_dir: str) -> IsolatedEnv:
        """Create a git worktree for the session.

        Args:
            session_id: Unique session identifier.
            base_dir: The project root (must be a git repo).

        Returns:
            IsolatedEnv with the worktree path and branch name.

        Raises:
            ValueError: If *base_dir* is not a git repository.
            RuntimeError: If the git worktree command fails.
        """
        if not _is_git_repo(base_dir):
            raise ValueError(f"Not a git repository: {base_dir}")

        worktree_path = os.path.join(
            str(get_strawpot_home()),
            "worktrees",
            _project_hash(base_dir),
            session_id,
        )
        branch = f"strawpot/{session_id}"

        result = _git(
            ["worktree", "add", worktree_path, "-b", branch],
            cwd=base_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed: {result.stderr.strip()}"
            )

        return IsolatedEnv(path=worktree_path, branch=branch)

    def cleanup(
        self,
        env: IsolatedEnv,
        *,
        base_dir: str,
        delete_branch: bool = True,
    ) -> None:
        """Remove the worktree and optionally delete the branch.

        Idempotent — safe to call even if the worktree was already removed.

        Args:
            env: The IsolatedEnv returned by :meth:`create`.
            base_dir: The original project root passed to :meth:`create`.
            delete_branch: If ``False``, keep the branch (e.g. for the PR
                strategy where the branch has been pushed to the remote).
        """
        # Remove the worktree (--force handles dirty worktrees)
        _git(["worktree", "remove", env.path, "--force"], cwd=base_dir)

        # Delete the branch if set and requested
        if env.branch and delete_branch:
            _git(["branch", "-D", env.branch], cwd=base_dir)
