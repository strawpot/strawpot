"""Tests for the discovery hint system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from strawpot.init.hint import (
    dismiss_init_hint,
    should_show_init_hint,
    show_init_hint,
)


@pytest.fixture()
def hint_home(tmp_path, monkeypatch):
    """Patch get_strawpot_home for hint storage."""
    monkeypatch.setattr("strawpot.init.hint.get_strawpot_home", lambda: tmp_path)
    return tmp_path


class TestShouldShowInitHint:
    def test_shows_when_no_claude_md(self, hint_home, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        assert should_show_init_hint(project) is True

    def test_hidden_when_claude_md_exists(self, hint_home, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        (project / "CLAUDE.md").write_text("# Project")
        assert should_show_init_hint(project) is False

    def test_hidden_after_dismissal(self, hint_home, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        dismiss_init_hint(project)
        assert should_show_init_hint(project) is False

    def test_dismissal_persists(self, hint_home, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        dismiss_init_hint(project)

        # Should still be dismissed on next check
        assert should_show_init_hint(project) is False


class TestShowInitHint:
    def test_prints_hint(self, capsys):
        show_init_hint()
        output = capsys.readouterr().out
        assert "strawpot init" in output
        assert "Tip" in output


class TestDismissInitHint:
    def test_creates_hints_file(self, hint_home, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        dismiss_init_hint(project)

        hints_path = hint_home / "hints.json"
        assert hints_path.exists()

    def test_multiple_projects(self, hint_home, tmp_path):
        p1 = tmp_path / "project1"
        p1.mkdir()
        p2 = tmp_path / "project2"
        p2.mkdir()

        dismiss_init_hint(p1)
        dismiss_init_hint(p2)

        assert should_show_init_hint(p1) is False
        assert should_show_init_hint(p2) is False
