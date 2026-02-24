"""Tests for lt init (core.commands.init_cmd)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.commands.init_cmd import run_init


class TestRunInit:
    def test_creates_loguetown_directory(self, tmp_path: Path):
        run_init(tmp_path)
        assert (tmp_path / ".loguetown").is_dir()

    def test_creates_subdirectories(self, tmp_path: Path):
        run_init(tmp_path)
        lt = tmp_path / ".loguetown"
        assert (lt / "roles").is_dir()
        assert (lt / "agents").is_dir()
        assert (lt / "skills").is_dir()

    def test_creates_project_yaml(self, tmp_path: Path):
        run_init(tmp_path)
        project_yaml = tmp_path / ".loguetown" / "project.yaml"
        assert project_yaml.exists()
        data = yaml.safe_load(project_yaml.read_text())
        assert "project" in data
        assert data["project"]["name"] == tmp_path.name

    def test_creates_default_roles(self, tmp_path: Path):
        run_init(tmp_path)
        roles_dir = tmp_path / ".loguetown" / "roles"
        role_names = {p.stem for p in roles_dir.glob("*.yaml")}
        assert role_names == {"planner", "implementer", "reviewer", "fixer", "documenter"}

    def test_roles_are_valid_yaml(self, tmp_path: Path):
        run_init(tmp_path)
        roles_dir = tmp_path / ".loguetown" / "roles"
        for p in roles_dir.glob("*.yaml"):
            data = yaml.safe_load(p.read_text())
            assert "name" in data

    def test_creates_gitignore_entry(self, tmp_path: Path):
        run_init(tmp_path)
        gi = tmp_path / ".gitignore"
        assert gi.exists()
        assert ".loguetown/runtime/" in gi.read_text()

    def test_appends_to_existing_gitignore(self, tmp_path: Path):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n__pycache__/\n")
        run_init(tmp_path)
        content = gi.read_text()
        assert "*.pyc" in content
        assert ".loguetown/runtime/" in content

    def test_does_not_duplicate_gitignore_entry(self, tmp_path: Path):
        gi = tmp_path / ".gitignore"
        gi.write_text(".loguetown/runtime/\n")
        run_init(tmp_path)
        content = gi.read_text()
        assert content.count(".loguetown/runtime/") == 1

    def test_fails_if_already_exists(self, tmp_path: Path):
        run_init(tmp_path)
        with pytest.raises(SystemExit):
            run_init(tmp_path)

    def test_force_does_not_overwrite(self, tmp_path: Path):
        run_init(tmp_path)
        # Modify project.yaml
        project_yaml = tmp_path / ".loguetown" / "project.yaml"
        original = project_yaml.read_text()
        project_yaml.write_text("# modified\n" + original)
        run_init(tmp_path, force=True)
        # Should not have been overwritten
        assert project_yaml.read_text().startswith("# modified")

    def test_force_adds_missing_roles(self, tmp_path: Path):
        run_init(tmp_path)
        # Delete one role
        (tmp_path / ".loguetown" / "roles" / "fixer.yaml").unlink()
        run_init(tmp_path, force=True)
        assert (tmp_path / ".loguetown" / "roles" / "fixer.yaml").exists()
