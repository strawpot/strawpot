"""Tests for core.workdir.resolve_workdir."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.workdir import WorkdirError, resolve_workdir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(base: Path) -> Path:
    """Create a minimal strawpot project under *base*."""
    (base / ".strawpot").mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# CWD walk-up resolution
# ---------------------------------------------------------------------------


def test_finds_strawpot_in_cwd(tmp_path: Path):
    _make_project(tmp_path)
    result = resolve_workdir(cwd=tmp_path)
    assert result == tmp_path


def test_walks_up_from_subdirectory(tmp_path: Path):
    _make_project(tmp_path)
    subdir = tmp_path / "src" / "components"
    subdir.mkdir(parents=True)
    result = resolve_workdir(cwd=subdir)
    assert result == tmp_path


def test_walks_up_multiple_levels(tmp_path: Path):
    _make_project(tmp_path)
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    result = resolve_workdir(cwd=deep)
    assert result == tmp_path


def test_raises_when_no_strawpot_found(tmp_path: Path):
    with pytest.raises(WorkdirError, match="not in a strawpot project"):
        resolve_workdir(cwd=tmp_path)


def test_error_message_suggests_lt_init(tmp_path: Path):
    with pytest.raises(WorkdirError, match="lt init"):
        resolve_workdir(cwd=tmp_path)


def test_nested_projects_finds_nearest(tmp_path: Path):
    """Nested .strawpot/ — should find the nearest ancestor."""
    outer = tmp_path / "outer"
    inner = tmp_path / "outer" / "inner"
    _make_project(outer)
    _make_project(inner)
    nested = inner / "src"
    nested.mkdir(parents=True)
    result = resolve_workdir(cwd=nested)
    assert result == inner


# ---------------------------------------------------------------------------
# $LT_WORKDIR override
# ---------------------------------------------------------------------------


def test_lt_workdir_env_takes_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "myproject"
    _make_project(project)
    monkeypatch.setenv("LT_WORKDIR", str(project))
    result = resolve_workdir(cwd=tmp_path)  # cwd has no .strawpot/
    assert result == project


def test_lt_workdir_env_fails_if_no_strawpot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("LT_WORKDIR", str(empty))
    with pytest.raises(WorkdirError, match="LT_WORKDIR"):
        resolve_workdir()


def test_lt_workdir_resolves_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "proj"
    _make_project(project)
    monkeypatch.setenv("LT_WORKDIR", str(project))
    result = resolve_workdir()
    assert result == project.resolve()
