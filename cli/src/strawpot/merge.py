"""Merge strategies — apply session changes at cleanup time.

Handles local patch application, PR creation, and auto-detection of the
appropriate strategy.  Called from ``Session.stop()`` for worktree (and
future docker) isolation modes.

Strategies
----------
- ``local`` — generate a unified diff patch from the session branch, apply
  it to the base branch in the project directory.  Conflicts are detected
  and the user is prompted for resolution.
- ``pr`` — push the session branch to the remote and create a pull request
  using the configured ``pr_command`` template.
- ``auto`` — detect a remote (``git remote get-url origin``): use ``pr``
  if a remote exists, otherwise fall back to ``local``.
"""

import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Types
# ------------------------------------------------------------------


@dataclass
class MergeResult:
    """Outcome of a merge operation."""

    strategy: str  # "local", "pr", or "none"
    success: bool
    message: str  # human-readable summary
    pr_url: str | None = None


# ------------------------------------------------------------------
# Git helpers
# ------------------------------------------------------------------


def _git(args: list[str], cwd: str, **kwargs) -> subprocess.CompletedProcess:
    """Run a git command in *cwd*."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        **kwargs,
    )


def _has_remote(cwd: str) -> bool:
    """Return ``True`` if the repo at *cwd* has an ``origin`` remote."""
    result = _git(["remote", "get-url", "origin"], cwd=cwd)
    return result.returncode == 0


def _is_git_repo(path: str) -> bool:
    """Return ``True`` if *path* is inside a git repository."""
    result = _git(["rev-parse", "--git-dir"], cwd=path)
    return result.returncode == 0


# ------------------------------------------------------------------
# Strategy resolution
# ------------------------------------------------------------------


def resolve_strategy(strategy: str, base_dir: str) -> str:
    """Resolve ``"auto"`` to ``"local"`` or ``"pr"``.

    Args:
        strategy: One of ``"auto"``, ``"local"``, ``"pr"``.
        base_dir: Project root directory.

    Returns:
        ``"local"`` or ``"pr"``.
    """
    if strategy == "auto":
        return "pr" if _has_remote(base_dir) else "local"
    return strategy


# ------------------------------------------------------------------
# External tool validation
# ------------------------------------------------------------------


def _ensure_patch_available() -> None:
    """Raise RuntimeError if the ``patch`` command is not on PATH.

    Called before using ``patch`` for non-git directories.
    """
    if shutil.which("patch") is None:
        raise RuntimeError(
            "The 'patch' command is required for non-git directories. "
            "Install it via your package manager "
            "(e.g. 'apt install patch' or 'brew install gpatch')."
        )


# ------------------------------------------------------------------
# Patch helpers
# ------------------------------------------------------------------


def _generate_patch(
    base_branch: str, session_branch: str, cwd: str
) -> str:
    """Generate a unified diff from *base_branch* to *session_branch*.

    Runs in *cwd* (typically the worktree) which has access to both
    branches.  Returns the patch text — may be empty if no changes.
    """
    result = _git(
        ["diff", f"{base_branch}..{session_branch}"],
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to generate patch: {result.stderr.strip()}"
        )
    return result.stdout


def _check_patch(patch: str, cwd: str) -> list[str]:
    """Dry-run patch application and return conflicting file paths.

    An empty list means the patch applies cleanly.

    Uses ``git apply --check`` for git repos, ``patch --dry-run``
    otherwise.
    """
    if not patch.strip():
        return []

    patch_bytes = patch.encode("utf-8")

    if _is_git_repo(cwd):
        result = subprocess.run(
            ["git", "apply", "--check"],
            input=patch_bytes,
            cwd=cwd,
            capture_output=True,
        )
        if result.returncode == 0:
            return []
        stderr = result.stderr.decode("utf-8", errors="replace")
        conflicts: list[str] = []
        for line in stderr.splitlines():
            if "patch failed:" in line:
                parts = line.split("patch failed:")
                if len(parts) > 1:
                    file_part = parts[1].strip()
                    file_path = file_part.rsplit(":", 1)[0]
                    if file_path not in conflicts:
                        conflicts.append(file_path)
        return conflicts if conflicts else ["(unknown files)"]

    # Non-git host: use patch --dry-run.
    result = subprocess.run(
        ["patch", "--dry-run", "-p1"],
        input=patch_bytes,
        cwd=cwd,
        capture_output=True,
    )
    if result.returncode == 0:
        return []
    stdout = result.stdout.decode("utf-8", errors="replace")
    conflicts = []
    for line in stdout.splitlines():
        if line.startswith("patching file "):
            fname = line.removeprefix("patching file ").strip()
            if fname not in conflicts:
                conflicts.append(fname)
    return conflicts if conflicts else ["(unknown files)"]


def _apply_patch(patch: str, cwd: str) -> bool:
    """Apply a patch cleanly (no conflict handling).

    Uses ``git apply`` for git repos, ``patch -p1`` otherwise.
    Returns ``True`` on success.
    """
    patch_bytes = patch.encode("utf-8")
    if _is_git_repo(cwd):
        result = subprocess.run(
            ["git", "apply"],
            input=patch_bytes,
            cwd=cwd,
            capture_output=True,
        )
    else:
        result = subprocess.run(
            ["patch", "-p1"],
            input=patch_bytes,
            cwd=cwd,
            capture_output=True,
        )
    return result.returncode == 0


def _apply_patch_all(patch: str, cwd: str) -> bool:
    """Apply patch, overriding conflicts with session's changes.

    Uses ``git apply --3way`` for git repos, ``patch --force`` otherwise.
    """
    patch_bytes = patch.encode("utf-8")
    if _is_git_repo(cwd):
        result = subprocess.run(
            ["git", "apply", "--3way"],
            input=patch_bytes,
            cwd=cwd,
            capture_output=True,
        )
    else:
        result = subprocess.run(
            ["patch", "--force", "-p1"],
            input=patch_bytes,
            cwd=cwd,
            capture_output=True,
        )
    return result.returncode == 0


def _apply_patch_skip(patch: str, cwd: str) -> bool:
    """Apply patch, skipping conflicting hunks.

    Uses ``git apply --reject`` for git repos (then cleans up ``.rej``
    files), ``patch -p1`` for non-git (skips failed hunks by default).
    """
    patch_bytes = patch.encode("utf-8")
    if _is_git_repo(cwd):
        subprocess.run(
            ["git", "apply", "--reject"],
            input=patch_bytes,
            cwd=cwd,
            capture_output=True,
        )
        # Clean up .rej files left by --reject
        for root, _dirs, files in os.walk(cwd):
            for f in files:
                if f.endswith(".rej"):
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass
    else:
        subprocess.run(
            ["patch", "-p1"],
            input=patch.encode("utf-8"),
            cwd=cwd,
            capture_output=True,
        )
    return True  # best-effort: non-conflicting parts applied


# ------------------------------------------------------------------
# Conflict resolution prompt
# ------------------------------------------------------------------


def _prompt_conflict_resolution(
    conflicts: list[str],
    echo=None,
    prompt=None,
) -> str:
    """Display conflict info and prompt the user for a resolution choice.

    Args:
        conflicts: Conflicting file paths.
        echo: Output callable (default: ``click.echo``).
        prompt: Input callable (default: ``click.prompt``).

    Returns:
        ``"a"`` (apply all), ``"s"`` (skip conflicts), or ``"d"``
        (discard all).
    """
    import click as _click

    _echo = echo or _click.echo
    _prompt = prompt or _click.prompt

    _echo("")
    _echo(
        f"Conflict: {len(conflicts)} file(s) changed on both "
        f"sides since session started."
    )
    for f in conflicts:
        _echo(f"  {f}")
    _echo("")
    _echo("  [a] Apply all — override conflicts with session's changes")
    _echo("  [s] Skip conflicts — apply only non-conflicting changes")
    _echo("  [d] Discard all — drop all session changes")
    _echo("")

    choice = _prompt(
        "Choose",
        type=_click.Choice(["a", "s", "d"]),
        default="d",
    )
    return choice


# ------------------------------------------------------------------
# Public: local strategy
# ------------------------------------------------------------------


def merge_local(
    *,
    base_branch: str,
    session_branch: str,
    worktree_dir: str,
    base_dir: str,
    echo=None,
    prompt=None,
) -> MergeResult:
    """Execute the **local** merge strategy.

    Generates a patch from *session_branch* vs *base_branch* (run in
    *worktree_dir* which has access to both), then applies it to
    *base_dir*.

    Args:
        base_branch: Branch the session diverged from.
        session_branch: The session's worktree branch.
        worktree_dir: Path to the worktree (used for ``git diff``).
        base_dir: Project root where the patch is applied.
        echo: Output callable (for testing).
        prompt: Input callable (for testing).
    """
    patch = _generate_patch(base_branch, session_branch, cwd=worktree_dir)

    if not patch.strip():
        return MergeResult(
            strategy="local",
            success=True,
            message="No changes to apply.",
        )

    if not _is_git_repo(base_dir):
        _ensure_patch_available()

    conflicts = _check_patch(patch, cwd=base_dir)

    if not conflicts:
        ok = _apply_patch(patch, cwd=base_dir)
        return MergeResult(
            strategy="local",
            success=ok,
            message="Changes applied cleanly."
            if ok
            else "Patch apply failed.",
        )

    # Conflicts — ask the user
    choice = _prompt_conflict_resolution(conflicts, echo=echo, prompt=prompt)

    if choice == "a":
        ok = _apply_patch_all(patch, base_dir)
        return MergeResult(
            strategy="local",
            success=ok,
            message="All changes applied (conflicts overridden).",
        )
    if choice == "s":
        _apply_patch_skip(patch, base_dir)
        return MergeResult(
            strategy="local",
            success=True,
            message="Non-conflicting changes applied, conflicts skipped.",
        )
    # "d"
    return MergeResult(
        strategy="local",
        success=True,
        message="All session changes discarded.",
    )


# ------------------------------------------------------------------
# Public: PR strategy
# ------------------------------------------------------------------


def merge_pr(
    *,
    base_branch: str,
    session_branch: str,
    worktree_dir: str,
    base_dir: str,
    pr_command: str,
    echo=None,
) -> MergeResult:
    """Execute the **PR** merge strategy.

    Commits any uncommitted changes in the worktree, pushes the branch
    to the remote, and creates a PR using the configured *pr_command*
    template.

    Args:
        base_branch: Branch the session diverged from.
        session_branch: The session's worktree branch.
        worktree_dir: Path to the worktree.
        base_dir: Project root.
        pr_command: PR creation command template with ``{base_branch}``
            and ``{session_branch}`` placeholders.
        echo: Output callable (for testing).
    """
    import click as _click

    _echo = echo or _click.echo

    # 1. Commit any uncommitted changes
    status = _git(["status", "--porcelain"], cwd=worktree_dir)
    if status.stdout.strip():
        _git(["add", "-A"], cwd=worktree_dir)
        _git(
            ["commit", "-m", "strawpot: uncommitted changes from session"],
            cwd=worktree_dir,
        )

    # 2. Push branch
    push = _git(
        ["push", "-u", "origin", session_branch],
        cwd=worktree_dir,
    )
    if push.returncode != 0:
        return MergeResult(
            strategy="pr",
            success=False,
            message=f"Failed to push branch: {push.stderr.strip()}",
        )

    # 3. Create PR (if command is non-empty)
    pr_url = None
    if pr_command.strip():
        cmd = pr_command.format(
            base_branch=base_branch,
            session_branch=session_branch,
        )
        tokens = shlex.split(cmd)
        pr_result = subprocess.run(
            tokens,
            cwd=base_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if pr_result.returncode == 0:
            pr_url = pr_result.stdout.strip()
            _echo(f"PR created: {pr_url}")
        else:
            _echo(f"PR creation failed: {pr_result.stderr.strip()}")
            return MergeResult(
                strategy="pr",
                success=True,
                message=(
                    "Branch pushed but PR creation failed: "
                    f"{pr_result.stderr.strip()}"
                ),
            )

    return MergeResult(
        strategy="pr",
        success=True,
        message="Branch pushed and PR created.",
        pr_url=pr_url,
    )
