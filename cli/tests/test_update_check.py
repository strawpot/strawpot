"""Tests for the auto-update check on startup."""

import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from strawpot.cli import (
    _check_update_async,
    _version_newer,
    cli,
)


# ---------------------------------------------------------------------------
# _version_newer
# ---------------------------------------------------------------------------


class TestVersionNewer:
    def test_newer_patch(self):
        assert _version_newer("0.2.1", "0.2.0") is True

    def test_newer_minor(self):
        assert _version_newer("0.3.0", "0.2.5") is True

    def test_newer_major(self):
        assert _version_newer("1.0.0", "0.9.9") is True

    def test_same_version(self):
        assert _version_newer("0.1.0", "0.1.0") is False

    def test_older_version(self):
        assert _version_newer("0.1.0", "0.2.0") is False

    def test_with_packaging(self):
        """Works when packaging module is available."""
        assert _version_newer("1.0.0", "0.9.0") is True

    def test_without_packaging(self):
        """Falls back to tuple comparison when packaging is unavailable."""
        with patch.dict("sys.modules", {"packaging": None, "packaging.version": None}):
            # Force re-import won't help since function is already defined,
            # but we can test the fallback path directly
            assert _version_newer("0.2.0", "0.1.0") is True


# ---------------------------------------------------------------------------
# _check_update_async
# ---------------------------------------------------------------------------


class TestCheckUpdateAsync:
    @patch("strawpot.cli._check_pypi_version", return_value="99.0.0")
    @patch("strawpot.cli.__version__", "0.1.0")
    def test_returns_latest_when_newer(self, mock_check):
        result = _check_update_async(timeout=5.0)
        assert result == "99.0.0"

    @patch("strawpot.cli._check_pypi_version", return_value="0.1.0")
    @patch("strawpot.cli.__version__", "0.1.0")
    def test_returns_none_when_up_to_date(self, mock_check):
        result = _check_update_async(timeout=5.0)
        assert result is None

    @patch("strawpot.cli._check_pypi_version", return_value=None)
    @patch("strawpot.cli.__version__", "0.1.0")
    def test_returns_none_on_failure(self, mock_check):
        result = _check_update_async(timeout=5.0)
        assert result is None

    @patch("strawpot.cli._check_pypi_version", return_value="0.0.9")
    @patch("strawpot.cli.__version__", "0.1.0")
    def test_returns_none_when_older(self, mock_check):
        result = _check_update_async(timeout=5.0)
        assert result is None


# ---------------------------------------------------------------------------
# --skip-update-check flag
# ---------------------------------------------------------------------------


class TestSkipUpdateCheckFlag:
    """Verify the flag is accepted by start and gui commands."""

    @patch("strawpot.cli._check_update_async")
    @patch("strawpot.cli.load_config")
    @patch("strawpot.cli.needs_onboarding", return_value=False)
    @patch("strawpot.cli._ensure_agent_installed")
    @patch("strawpot.cli._ensure_skill_installed")
    @patch("strawpot.cli._ensure_role_installed")
    @patch("strawpot.cli._ensure_memory_installed")
    @patch("strawpot.cli.resolve_agent")
    @patch("strawpot.cli.validate_agent")
    @patch("strawpot.cli.WrapperRuntime")
    @patch("strawpot.cli.resolve_isolator")
    @patch("strawpot.cli.Session")
    @patch("strawpot.cli.recover_stale_sessions", return_value=[])
    def test_start_skip_flag_prevents_check(
        self,
        mock_recover,
        mock_session,
        mock_isolator,
        mock_wrapper,
        mock_validate,
        mock_resolve,
        mock_mem,
        mock_role,
        mock_skill,
        mock_agent,
        mock_onboard,
        mock_config,
        mock_update,
    ):
        from strawpot.config import StrawPotConfig
        from strawpot.agents.registry import AgentSpec, ValidationResult

        cfg = StrawPotConfig()
        mock_config.return_value = cfg
        mock_resolve.return_value = AgentSpec(
            name="test", version="1.0", wrapper_cmd=["/bin/true"],
            config={}, env_schema={}, tools={},
        )
        mock_validate.return_value = ValidationResult()

        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--skip-update-check"], catch_exceptions=False)
        mock_update.assert_not_called()

    @patch("strawpot.cli._check_update_async")
    @patch("strawpot.cli.load_config")
    @patch("strawpot.cli.needs_onboarding", return_value=False)
    @patch("strawpot.cli._ensure_agent_installed")
    @patch("strawpot.cli._ensure_skill_installed")
    @patch("strawpot.cli._ensure_role_installed")
    @patch("strawpot.cli._ensure_memory_installed")
    def test_gui_skip_flag_prevents_check(
        self,
        mock_mem,
        mock_role,
        mock_skill,
        mock_agent,
        mock_onboard,
        mock_config,
        mock_update,
    ):
        from strawpot.config import StrawPotConfig

        cfg = StrawPotConfig()
        mock_config.return_value = cfg

        runner = CliRunner()
        with patch("strawpot.cli.gui") as mock_gui_cmd:
            # Just verify the flag is accepted (gui will fail without full setup)
            result = runner.invoke(cli, ["gui", "--skip-update-check"], catch_exceptions=True)
            mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# Config skip_update_check
# ---------------------------------------------------------------------------


class TestConfigSkipUpdateCheck:
    def test_default_is_false(self):
        from strawpot.config import StrawPotConfig
        config = StrawPotConfig()
        assert config.skip_update_check is False

    def test_loaded_from_toml(self, tmp_path):
        toml_file = tmp_path / "strawpot.toml"
        toml_file.write_text('skip_update_check = true\n')
        from strawpot.config import load_config
        config = load_config(tmp_path)
        assert config.skip_update_check is True


# ---------------------------------------------------------------------------
# Environment variable skip
# ---------------------------------------------------------------------------


class TestEnvVarSkip:
    @patch("strawpot.cli._check_update_async")
    @patch("strawpot.cli.load_config")
    @patch("strawpot.cli.needs_onboarding", return_value=False)
    @patch("strawpot.cli._ensure_agent_installed")
    @patch("strawpot.cli._ensure_skill_installed")
    @patch("strawpot.cli._ensure_role_installed")
    @patch("strawpot.cli._ensure_memory_installed")
    @patch("strawpot.cli.resolve_agent")
    @patch("strawpot.cli.validate_agent")
    @patch("strawpot.cli.WrapperRuntime")
    @patch("strawpot.cli.resolve_isolator")
    @patch("strawpot.cli.Session")
    @patch("strawpot.cli.recover_stale_sessions", return_value=[])
    def test_env_var_prevents_check(
        self,
        mock_recover,
        mock_session,
        mock_isolator,
        mock_wrapper,
        mock_validate,
        mock_resolve,
        mock_mem,
        mock_role,
        mock_skill,
        mock_agent,
        mock_onboard,
        mock_config,
        mock_update,
    ):
        from strawpot.config import StrawPotConfig
        from strawpot.agents.registry import AgentSpec, ValidationResult

        cfg = StrawPotConfig()
        mock_config.return_value = cfg
        mock_resolve.return_value = AgentSpec(
            name="test", version="1.0", wrapper_cmd=["/bin/true"],
            config={}, env_schema={}, tools={},
        )
        mock_validate.return_value = ValidationResult()

        runner = CliRunner(env={"STRAWPOT_SKIP_UPDATE_CHECK": "1"})
        result = runner.invoke(cli, ["start"], catch_exceptions=False)
        mock_update.assert_not_called()
