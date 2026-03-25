"""Merge — apply worktree session changes at cleanup time.

Detects what the agent actually did and acts accordingly:

- **PR created** — the work product is the PR; nothing to merge locally,
  just clean up the worktree.
- **No PR, clean merge** — generate a unified diff patch from the session
  branch and apply it to the base branch as unstaged changes.
- **No PR, conflicts** — in interactive mode, prompt the user for
  resolution.  In headless mode, export the diff as a ``.patch`` file
  under ``.strawpot/patches/`` so no work is silently lost.

Called from ``Session.stop()`` for worktree isolation.
"""

import logging
import os
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

    success: bool
    message: str  # human-readable summary


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


def _is_git_repo(path: str) -> bool:
    """Return ``True`` if *path* is inside a git repository."""
    result = _git(["rev-parse", "--git-dir"], cwd=path)
    return result.returncode == 0


# ------------------------------------------------------------------
# PR detection
# ------------------------------------------------------------------


def detect_pr_created(session_branch: str, base_dir: str) -> bool:
    """Return ``True`` if *session_branch* has an open pull request.

    Uses ``gh pr list`` when available.  Returns ``False`` when ``gh``
    is not installed or the check fails — the safe default is to
    patch-apply changes rather than silently discard them.
    """
    if not shutil.which("gh"):
        logger.debug("gh CLI not found — assuming no PR created")
        return False
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--head", session_branch, "--state", "open",
             "--json", "number", "--limit", "1"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip() not in ("", "[]")
        logger.debug(
            "gh pr list failed (exit %d) for %s",
            result.returncode,
            session_branch,
        )
        return False
    except Exception:
        logger.debug("gh pr list check failed for %s", session_branch, exc_info=True)
        return False


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
# Patch-file preservation (headless conflict fallback)
# ------------------------------------------------------------------


def save_patch_file(patch: str, patch_dir: str, session_id: str) -> str:
    """Write *patch* to ``<patch_dir>/<session_id>.patch``.

    Creates *patch_dir* if it does not exist.  Returns the absolute path
    to the saved file.
    """
    os.makedirs(patch_dir, exist_ok=True)
    patch_path = os.path.join(patch_dir, f"{session_id}.patch")
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(patch)
    return patch_path


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
# Public: local patch-apply
# ------------------------------------------------------------------


def merge_local(
    *,
    base_branch: str,
    session_branch: str,
    worktree_dir: str,
    base_dir: str,
    echo=None,
    prompt=None,
    patch_save_dir: str | None = None,
    session_id: str | None = None,
) -> MergeResult:
    """Patch-apply session changes as unstaged changes to *base_dir*.

    Generates a patch from *session_branch* vs *base_branch* (run in
    *worktree_dir* which has access to both), then applies it to
    *base_dir*.

    When *patch_save_dir* and *session_id* are provided and conflicts
    are detected, the diff is saved as a ``.patch`` file instead of
    prompting the user.  This is the headless/agent-mode fallback that
    prevents silent data loss.

    Args:
        base_branch: Branch the session diverged from.
        session_branch: The session's worktree branch.
        worktree_dir: Path to the worktree (used for ``git diff``).
        base_dir: Project root where the patch is applied.
        echo: Output callable (for testing).
        prompt: Input callable (for testing).
        patch_save_dir: Directory to save ``.patch`` files on conflict
            (headless mode).  When ``None``, falls back to interactive
            prompt.
        session_id: Session identifier used as the patch filename.
            Required when *patch_save_dir* is set.
    """
    patch = _generate_patch(base_branch, session_branch, cwd=worktree_dir)

    if not patch.strip():
        return MergeResult(
            success=True,
            message="No changes to apply.",
        )

    if not _is_git_repo(base_dir):
        _ensure_patch_available()

    conflicts = _check_patch(patch, cwd=base_dir)

    if not conflicts:
        ok = _apply_patch(patch, cwd=base_dir)
        return MergeResult(
            success=ok,
            message="Changes applied cleanly."
            if ok
            else "Patch apply failed.",
        )

    # ------------------------------------------------------------------
    # Conflicts detected
    # ------------------------------------------------------------------

    if bool(patch_save_dir) != bool(session_id):
        raise ValueError(
            "patch_save_dir and session_id must both be set or both be None"
        )

    # Headless mode: save patch file instead of prompting
    if patch_save_dir and session_id:
        conflict_list = ", ".join(conflicts)
        try:
            patch_path = save_patch_file(patch, patch_save_dir, session_id)
        except OSError:
            logger.error(
                "Failed to save patch file to %s/%s.patch — "
                "changes exist on branch but patch could not be written",
                patch_save_dir,
                session_id,
                exc_info=True,
            )
            return MergeResult(
                success=False,
                message=(
                    f"Merge conflict: {len(conflicts)} file(s). "
                    f"Patch save FAILED — recover changes from the "
                    f"session branch manually."
                ),
            )
        logger.warning(
            "Merge conflict — patch saved to %s (conflicts: %s)",
            patch_path,
            conflict_list,
        )
        return MergeResult(
            success=False,
            message=(
                f"Merge conflict: {len(conflicts)} file(s). "
                f"Patch saved to {patch_path}"
            ),
        )

    # Interactive mode: ask the user
    choice = _prompt_conflict_resolution(conflicts, echo=echo, prompt=prompt)

    if choice == "a":
        ok = _apply_patch_all(patch, base_dir)
        return MergeResult(
            success=ok,
            message="All changes applied (conflicts overridden).",
        )
    if choice == "s":
        _apply_patch_skip(patch, base_dir)
        return MergeResult(
            success=True,
            message="Non-conflicting changes applied, conflicts skipped.",
        )
    # "d"
    return MergeResult(
        success=True,
        message="All session changes discarded.",
    )
