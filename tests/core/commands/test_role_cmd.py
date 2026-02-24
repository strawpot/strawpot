"""Tests for lt role commands (core.commands.role_cmd)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.commands.role_cmd import (
    _cmd_create,
    _cmd_delete,
    _cmd_list,
    _cmd_show,
    _list_role_names,
    _role_path,
)
from core.roles.types import Role


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Minimal loguetown project with a roles/ directory."""
    roles_dir = tmp_path / ".loguetown" / "roles"
    roles_dir.mkdir(parents=True)
    # Create two roles
    for name, desc in [("implementer", "Writes code"), ("reviewer", "Reviews diffs")]:
        Role(name=name, description=desc).to_yaml(roles_dir / f"{name}.yaml")
    return tmp_path


# ---------------------------------------------------------------------------
# _list_role_names
# ---------------------------------------------------------------------------


def test_list_role_names(project: Path):
    names = _list_role_names(project)
    assert set(names) == {"implementer", "reviewer"}


def test_list_role_names_empty(tmp_path: Path):
    (tmp_path / ".loguetown" / "roles").mkdir(parents=True)
    assert _list_role_names(tmp_path) == []


def test_list_role_names_no_dir(tmp_path: Path):
    assert _list_role_names(tmp_path) == []


# ---------------------------------------------------------------------------
# _cmd_list
# ---------------------------------------------------------------------------


def test_cmd_list_prints_roles(project: Path, capsys):
    _cmd_list(project)
    out = capsys.readouterr().out
    assert "implementer" in out
    assert "reviewer" in out


def test_cmd_list_includes_description(project: Path, capsys):
    _cmd_list(project)
    out = capsys.readouterr().out
    assert "Writes code" in out


def test_cmd_list_empty(tmp_path: Path, capsys):
    (tmp_path / ".loguetown" / "roles").mkdir(parents=True)
    _cmd_list(tmp_path)
    out = capsys.readouterr().out
    assert "No roles" in out


# ---------------------------------------------------------------------------
# _cmd_show
# ---------------------------------------------------------------------------


def test_cmd_show_prints_yaml(project: Path, capsys):
    _cmd_show(project, "implementer")
    out = capsys.readouterr().out
    assert "implementer" in out


def test_cmd_show_missing_role_exits(project: Path):
    with pytest.raises(SystemExit):
        _cmd_show(project, "nonexistent")


# ---------------------------------------------------------------------------
# _cmd_create
# ---------------------------------------------------------------------------


def test_cmd_create_creates_file(project: Path):
    _cmd_create(project, "fixer")
    path = _role_path(project, "fixer")
    assert path.exists()


def test_cmd_create_file_is_valid_yaml(project: Path):
    _cmd_create(project, "fixer")
    data = yaml.safe_load(_role_path(project, "fixer").read_text())
    assert data["name"] == "fixer"


def test_cmd_create_duplicate_exits(project: Path):
    with pytest.raises(SystemExit):
        _cmd_create(project, "implementer")


# ---------------------------------------------------------------------------
# _cmd_delete
# ---------------------------------------------------------------------------


def test_cmd_delete_removes_file(project: Path):
    _cmd_delete(project, "reviewer")
    assert not _role_path(project, "reviewer").exists()


def test_cmd_delete_missing_exits(project: Path):
    with pytest.raises(SystemExit):
        _cmd_delete(project, "nonexistent")


def test_cmd_delete_warns_if_agents_use_role(project: Path, capsys):
    # Create an agent that uses 'implementer'
    agents_dir = project / ".loguetown" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "charlie.yaml").write_text(
        yaml.dump({"name": "charlie", "role": "implementer"})
    )
    _cmd_delete(project, "implementer")
    err = capsys.readouterr().err
    assert "charlie" in err
