"""Tests for lt skills commands (core.commands.skills_cmd)."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.commands.skills_cmd import (
    _cmd_install,
    _cmd_list,
    _cmd_remove,
    _cmd_show,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Minimal loguetown project with some skill modules."""
    project_pool = tmp_path / ".loguetown" / "skills"
    project_pool.mkdir(parents=True)

    # Create two project skill modules
    (project_pool / "commit-conventions").mkdir()
    (project_pool / "commit-conventions" / "README.md").write_text(
        "# Commit Conventions\n\nUse conventional commits.\n"
    )

    (project_pool / "project-overview").mkdir()
    (project_pool / "project-overview" / "architecture.md").write_text(
        "---\ndescription: High-level architecture\n---\n\n# Architecture\n\nContent.\n"
    )

    return tmp_path


@pytest.fixture
def global_root(tmp_path: Path) -> Path:
    global_pool = tmp_path / "global_home" / "skills"
    global_pool.mkdir(parents=True)

    (global_pool / "personal-style").mkdir()
    (global_pool / "personal-style" / "style.md").write_text(
        "# Personal Style\n\nMy coding style.\n"
    )

    return tmp_path / "global_home"


# ---------------------------------------------------------------------------
# _cmd_install
# ---------------------------------------------------------------------------


def test_install_creates_directory(project: Path):
    pool = project / ".loguetown" / "skills"
    _cmd_install("react-patterns", "project", pool)
    assert (pool / "react-patterns").is_dir()


def test_install_creates_readme(project: Path):
    pool = project / ".loguetown" / "skills"
    _cmd_install("react-patterns", "project", pool)
    readme = pool / "react-patterns" / "README.md"
    assert readme.exists()
    assert "React Patterns" in readme.read_text()


def test_install_creates_parent_dirs(tmp_path: Path):
    pool = tmp_path / "does" / "not" / "exist"
    _cmd_install("my-skill", "project", pool)
    assert (pool / "my-skill").is_dir()


def test_install_fails_if_module_exists(project: Path):
    pool = project / ".loguetown" / "skills"
    with pytest.raises(SystemExit):
        _cmd_install("commit-conventions", "project", pool)


# ---------------------------------------------------------------------------
# _cmd_remove
# ---------------------------------------------------------------------------


def test_remove_deletes_directory(project: Path):
    pool = project / ".loguetown" / "skills"
    _cmd_remove("commit-conventions", "project", pool)
    assert not (pool / "commit-conventions").exists()


def test_remove_fails_if_not_found(project: Path):
    pool = project / ".loguetown" / "skills"
    with pytest.raises(SystemExit):
        _cmd_remove("nonexistent", "project", pool)


# ---------------------------------------------------------------------------
# _cmd_show
# ---------------------------------------------------------------------------


def test_show_prints_md_content(project: Path, capsys):
    pool = project / ".loguetown" / "skills"
    _cmd_show("commit-conventions", "project", pool)
    out = capsys.readouterr().out
    assert "conventional commits" in out.lower() or "commit" in out.lower()


def test_show_multiple_md_files(tmp_path: Path, capsys):
    pool = tmp_path / "skills"
    mod = pool / "my-skill"
    mod.mkdir(parents=True)
    (mod / "guide.md").write_text("# Guide\n\nContent A.\n")
    (mod / "examples.md").write_text("# Examples\n\nContent B.\n")
    _cmd_show("my-skill", "project", pool)
    out = capsys.readouterr().out
    assert "Content A" in out
    assert "Content B" in out


def test_show_fails_if_not_found(project: Path):
    pool = project / ".loguetown" / "skills"
    with pytest.raises(SystemExit):
        _cmd_show("nonexistent", "project", pool)


def test_show_no_md_files(tmp_path: Path, capsys):
    pool = tmp_path / "skills"
    mod = pool / "empty-skill"
    mod.mkdir(parents=True)
    _cmd_show("empty-skill", "project", pool)
    out = capsys.readouterr().out
    assert "No .md files" in out


# ---------------------------------------------------------------------------
# _cmd_list (integration)
# ---------------------------------------------------------------------------


def test_list_project_view_shows_global_and_project(project: Path, global_root: Path, capsys):
    _cmd_list(
        workdir=project,
        global_only=False,
        agent_name=None,
        global_root=global_root,
    )
    out = capsys.readouterr().out
    assert "commit-conventions" in out
    assert "personal-style" in out


def test_list_global_only(project: Path, global_root: Path, capsys):
    _cmd_list(
        workdir=project,
        global_only=True,
        agent_name=None,
        global_root=global_root,
    )
    out = capsys.readouterr().out
    assert "personal-style" in out
    # Project modules should not appear
    assert "commit-conventions" not in out


def test_list_agent_view_shows_all_three(tmp_path: Path, global_root: Path, capsys):
    # Set up agent pool
    agent_pool = tmp_path / ".loguetown" / "skills" / "charlie"
    agent_pool.mkdir(parents=True)
    (agent_pool / "ts-patterns").mkdir()
    (agent_pool / "ts-patterns" / "guide.md").write_text("# TS Patterns\n")

    # Project pool
    project_pool = tmp_path / ".loguetown" / "skills"
    (project_pool / "commit-guide").mkdir()
    (project_pool / "commit-guide" / "guide.md").write_text("# Commits\n")

    _cmd_list(
        workdir=tmp_path,
        global_only=False,
        agent_name="charlie",
        global_root=global_root,
    )
    out = capsys.readouterr().out
    assert "ts-patterns" in out
    assert "commit-guide" in out
    assert "personal-style" in out


def test_list_empty_shows_message(tmp_path: Path, global_root: Path, capsys):
    # Empty project pool
    (tmp_path / ".loguetown" / "skills").mkdir(parents=True)
    # global_root fixture already created ~/.loguetown/skills/ with a module;
    # use a fresh global root with an empty skills dir
    empty_global = tmp_path / "empty_global"
    (empty_global / "skills").mkdir(parents=True)
    global_root = empty_global
    _cmd_list(
        workdir=tmp_path,
        global_only=False,
        agent_name=None,
        global_root=global_root,
    )
    out = capsys.readouterr().out
    assert "No skill modules" in out
