"""Tests for strawpot.scheduler.store and MCP scheduling tools."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from strawpot.cli import cli
from strawpot.scheduler.store import ScheduleStore


# -- ScheduleStore CRUD -------------------------------------------------------


class TestScheduleStore:
    @pytest.fixture
    def store(self, tmp_path):
        return ScheduleStore(project_dir=str(tmp_path))

    def test_create_schedule(self, store):
        sched = store.create(
            name="Daily review",
            task="Review open PRs",
            cron="0 8 * * *",
            role="pr-reviewer",
        )
        assert sched.schedule_id.startswith("sched_")
        assert sched.name == "Daily review"
        assert sched.cron == "0 8 * * *"

    def test_create_validates_cron(self, store):
        with pytest.raises(ValueError, match="Invalid cron"):
            store.create(name="Bad", task="task", cron="not a cron")

    def test_list_schedules(self, store):
        store.create(name="S1", task="Task 1", cron="0 8 * * *")
        store.create(name="S2", task="Task 2", cron="0 9 * * *")
        assert len(store.list_schedules()) == 2

    def test_list_empty(self, store):
        assert store.list_schedules() == []

    def test_get_schedule(self, store):
        created = store.create(name="Get test", task="task", cron="0 8 * * *")
        found = store.get(created.schedule_id)
        assert found is not None
        assert found.name == "Get test"

    def test_get_nonexistent(self, store):
        assert store.get("sched_missing") is None

    def test_delete_schedule(self, store):
        created = store.create(name="Delete me", task="task", cron="0 8 * * *")
        assert store.delete(created.schedule_id) is True
        assert store.list_schedules() == []

    def test_delete_nonexistent(self, store):
        assert store.delete("sched_missing") is False

    def test_next_run(self, store):
        sched = store.create(name="Next", task="task", cron="0 8 * * *")
        next_run = sched.next_run()
        assert next_run != ""
        assert "T08:00:00" in next_run

    def test_update_status(self, store):
        sched = store.create(name="Status", task="task", cron="0 8 * * *")
        store.update_status(sched.schedule_id, "success")
        updated = store.get(sched.schedule_id)
        assert updated.last_status == "success"
        assert updated.last_run != ""


# -- MCP scheduling tools -----------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mcp_provider():
    import strawpot.mcp.server as mod

    mod._provider = None
    yield
    mod._provider = None


@pytest.mark.asyncio
async def test_schedule_create_tool(tmp_path):
    mock_provider = MagicMock()
    with patch("strawpot.mcp.server.get_standalone_provider", return_value=mock_provider):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            from strawpot.mcp.server import call_tool

            result = await call_tool(
                "schedule_create",
                {"name": "Daily PR review", "task": "Review PRs", "cron": "0 8 * * *"},
            )
            assert not result.isError
            assert "sched_" in result.content[0].text


@pytest.mark.asyncio
async def test_schedule_list_tool(tmp_path):
    mock_provider = MagicMock()
    with patch("strawpot.mcp.server.get_standalone_provider", return_value=mock_provider):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            from strawpot.mcp.server import call_tool

            result = await call_tool("schedule_list", {})
            assert "No schedules" in result.content[0].text


@pytest.mark.asyncio
async def test_schedule_create_invalid_cron(tmp_path):
    mock_provider = MagicMock()
    with patch("strawpot.mcp.server.get_standalone_provider", return_value=mock_provider):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            from strawpot.mcp.server import call_tool

            result = await call_tool(
                "schedule_create",
                {"name": "Bad", "task": "task", "cron": "invalid"},
            )
            assert result.isError


# -- CLI schedule commands ----------------------------------------------------


class TestScheduleCLI:
    def _invoke(self, args, tmp_path):
        with patch(
            "strawpot.memory.standalone.detect_project_dir",
            return_value=str(tmp_path),
        ):
            runner = CliRunner()
            return runner.invoke(cli, ["schedule", *args])

    def test_create_and_list(self, tmp_path):
        result = self._invoke(
            ["create", "Review PRs", "--cron", "0 8 * * *"], tmp_path
        )
        assert result.exit_code == 0
        assert "Schedule created" in result.output

        result = self._invoke(["list"], tmp_path)
        assert result.exit_code == 0
        assert "Review PRs" in result.output

    def test_create_invalid_cron(self, tmp_path):
        result = self._invoke(
            ["create", "task", "--cron", "bad cron"], tmp_path
        )
        assert result.exit_code != 0

    def test_delete(self, tmp_path):
        result = self._invoke(
            ["create", "Delete me", "--cron", "0 8 * * *"], tmp_path
        )
        for line in result.output.splitlines():
            if "ID:" in line:
                sched_id = line.split("ID:")[1].strip()
                break

        result = self._invoke(["delete", sched_id], tmp_path)
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_list_empty(self, tmp_path):
        result = self._invoke(["list"], tmp_path)
        assert "No schedules" in result.output

    def test_list_json(self, tmp_path):
        self._invoke(["create", "JSON test", "--cron", "0 8 * * *"], tmp_path)
        result = self._invoke(["list", "--json"], tmp_path)
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "JSON test"
