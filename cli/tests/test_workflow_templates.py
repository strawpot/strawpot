"""Tests for workflow templates and template-based scheduling."""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from strawpot.cli import cli
from strawpot.scheduler.templates import (
    WorkflowTemplate,
    list_templates,
    load_template,
    validate_prerequisites,
)


# -- Template loading ---------------------------------------------------------


class TestTemplateLoading:
    def test_list_templates_returns_3(self):
        templates = list_templates()
        assert len(templates) == 3
        slugs = {t.slug for t in templates}
        assert slugs == {"pr-review", "issue-triage", "test-coverage"}

    def test_load_pr_review(self):
        tpl = load_template("pr-review")
        assert tpl is not None
        assert tpl.name == "Daily PR Review"
        assert tpl.default_cron == "0 8 * * *"
        assert tpl.role == "pr-reviewer"
        assert "pull request" in tpl.task.lower()
        assert "gh" in tpl.requires_tools

    def test_load_issue_triage(self):
        tpl = load_template("issue-triage")
        assert tpl is not None
        assert tpl.role == "github-triager"
        assert "0 9 * * 1" in tpl.default_cron

    def test_load_test_coverage(self):
        tpl = load_template("test-coverage")
        assert tpl is not None
        assert "pytest" in tpl.requires_tools
        assert tpl.role == ""

    def test_load_nonexistent(self):
        assert load_template("nonexistent") is None


# -- Prerequisite validation --------------------------------------------------


class TestValidatePrerequisites:
    @patch("strawpot.scheduler.templates.shutil.which", return_value="/usr/bin/gh")
    @patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"})
    def test_all_met(self, mock_which):
        tpl = load_template("pr-review")
        issues = validate_prerequisites(tpl)
        assert issues == []

    @patch("strawpot.scheduler.templates.shutil.which", return_value=None)
    def test_missing_tool(self, mock_which):
        tpl = load_template("pr-review")
        issues = validate_prerequisites(tpl)
        assert any("gh" in i for i in issues)

    @patch("strawpot.scheduler.templates.shutil.which", return_value="/usr/bin/gh")
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_env(self, mock_which):
        tpl = load_template("pr-review")
        issues = validate_prerequisites(tpl)
        assert any("GITHUB_TOKEN" in i for i in issues)


# -- CLI template commands ----------------------------------------------------


class TestTemplateCLI:
    def test_templates_command(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["schedule", "templates"])
        assert result.exit_code == 0
        assert "pr-review" in result.output
        assert "issue-triage" in result.output
        assert "test-coverage" in result.output

    def test_create_from_template(self, tmp_path):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli, ["schedule", "create", "--template", "pr-review"]
            )
            assert result.exit_code == 0
            assert "Schedule created" in result.output
            assert "pr-reviewer" in result.output

    def test_create_from_template_with_custom_cron(self, tmp_path):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["schedule", "create", "--template", "pr-review", "--cron", "0 10 * * *"],
            )
            assert result.exit_code == 0
            assert "0 10 * * *" in result.output

    def test_create_from_nonexistent_template(self, tmp_path):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli, ["schedule", "create", "--template", "nonexistent"]
            )
            assert result.exit_code != 0
            assert "not found" in result.output

    def test_create_without_task_or_template(self, tmp_path):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli, ["schedule", "create", "--cron", "0 8 * * *"]
            )
            assert result.exit_code != 0

    def test_integration_template_to_list(self, tmp_path):
        """Install template → verify it appears in schedule list."""
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            runner = CliRunner()
            runner.invoke(
                cli, ["schedule", "create", "--template", "issue-triage"]
            )
            result = runner.invoke(cli, ["schedule", "list", "--json"])
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["name"] == "Weekly Issue Triage"
