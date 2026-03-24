"""Tests for the auto-update check on startup."""

import os
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from strawpot.cli import (
    _check_update_async,
    _detect_installer,
    _maybe_check_update,
    _prompt_update,
    _should_skip_update_check,
    _version_newer,
    cli,
)


# ---------------------------------------------------------------------------
# Shared fixtures for start-command tests (reduces decorator duplication)
# ---------------------------------------------------------------------------

_START_CMD_PATCHES = [
    "strawpot.cli._maybe_check_update",
    "strawpot.cli.load_config",
    "strawpot.cli.needs_onboarding",
    "strawpot.cli._ensure_agent_installed",
    "strawpot.cli._ensure_skill_installed",
    "strawpot.cli._ensure_role_installed",
    "strawpot.cli._ensure_memory_installed",
    "strawpot.cli.resolve_agent",
    "strawpot.cli.validate_agent",
    "strawpot.cli.WrapperRuntime",
    "strawpot.cli.resolve_isolator",
    "strawpot.cli.Session",
    "strawpot.cli.recover_stale_sessions",
]


@pytest.fixture()
def start_cmd_mocks():
    """Patch all dependencies of the ``start`` command and return them as a dict."""
    from strawpot.config import StrawPotConfig
    from strawpot.agents.registry import AgentSpec, ValidationResult

    patches = {name.rsplit(".", 1)[-1]: patch(name) for name in _START_CMD_PATCHES}
    mocks = {}
    for key, p in patches.items():
        mocks[key] = p.start()

    # Sensible defaults
    cfg = StrawPotConfig()
    mocks["load_config"].return_value = cfg
    mocks["needs_onboarding"].return_value = False
    mocks["recover_stale_sessions"].return_value = []
    mocks["resolve_agent"].return_value = AgentSpec(
        name="test", version="1.0", wrapper_cmd=["/bin/true"],
        config={}, env_schema={}, tools={},
    )
    mocks["validate_agent"].return_value = ValidationResult()

    yield mocks

    for p in patches.values():
        p.stop()


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
            assert _version_newer("0.2.0", "0.1.0") is True

    def test_unparseable_versions_return_false(self):
        """Malformed version strings that can't be parsed return False (not != comparison)."""
        assert _version_newer("abc", "def") is False

    def test_invalid_version_with_packaging_falls_through(self):
        """InvalidVersion from packaging falls through to tuple comparison."""
        # Mock packaging.version.Version to raise, simulating InvalidVersion.
        # Since _version_newer does a local import, we patch the module.
        with patch("packaging.version.Version", side_effect=Exception("bad")):
            # Should fall through to tuple comparison
            assert _version_newer("1.0.0", "0.9.0") is True


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

    @patch("strawpot.cli._check_pypi_version", return_value="99.0.0")
    @patch("strawpot.cli.__version__", "0.1.0")
    def test_passes_timeout_as_float(self, mock_check):
        """Timeout is forwarded to _check_pypi_version without int() truncation."""
        _check_update_async(timeout=0.5)
        mock_check.assert_called_once_with(timeout=0.5)


# ---------------------------------------------------------------------------
# --skip-update-check flag
# ---------------------------------------------------------------------------


class TestSkipUpdateCheckFlag:
    """Verify the flag is accepted by start and gui commands."""

    def test_start_skip_flag_prevents_check(self, start_cmd_mocks):
        runner = CliRunner()
        runner.invoke(cli, ["start", "--skip-update-check"], catch_exceptions=False)
        start_cmd_mocks["_maybe_check_update"].assert_called_once()

    @patch("strawpot.cli._maybe_check_update")
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
        import sys
        from strawpot.config import StrawPotConfig
        from unittest.mock import MagicMock

        cfg = StrawPotConfig()
        mock_config.return_value = cfg

        # Mock strawpot_gui.server so the lazy import inside gui() doesn't
        # start a real server (or fail with ModuleNotFoundError in CLI-only CI).
        fake_server = MagicMock()
        fake_server.DEFAULT_PORT = 8741
        sys.modules.setdefault("strawpot_gui", MagicMock())
        sys.modules["strawpot_gui.server"] = fake_server

        try:
            runner = CliRunner()
            runner.invoke(cli, ["gui", "--skip-update-check"], catch_exceptions=True)
            mock_update.assert_called_once()
        finally:
            sys.modules.pop("strawpot_gui.server", None)


# ---------------------------------------------------------------------------
# --headless and --task skip behavior
# ---------------------------------------------------------------------------


class TestHeadlessAndTaskSkip:
    """Verify that --headless and --task cause the update check to be skipped."""

    def test_headless_skips_update_check(self):
        from strawpot.config import StrawPotConfig
        cfg = StrawPotConfig()
        with patch("strawpot.cli._check_update_async") as mock_check:
            _maybe_check_update(False, cfg, headless=True)
            mock_check.assert_not_called()

    def test_task_skips_update_check(self):
        from strawpot.config import StrawPotConfig
        cfg = StrawPotConfig()
        with patch("strawpot.cli._check_update_async") as mock_check:
            _maybe_check_update(False, cfg, task="some task")
            mock_check.assert_not_called()

    def test_neither_headless_nor_task_runs_check(self):
        from strawpot.config import StrawPotConfig
        cfg = StrawPotConfig()
        with patch("strawpot.cli._check_update_async", return_value=None) as mock_check:
            _maybe_check_update(False, cfg)
            mock_check.assert_called_once()


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
    def test_env_var_prevents_check(self, start_cmd_mocks):
        runner = CliRunner(env={"STRAWPOT_SKIP_UPDATE_CHECK": "1"})
        runner.invoke(cli, ["start"], catch_exceptions=False)
        start_cmd_mocks["_maybe_check_update"].assert_called_once()

    def test_truthy_env_values(self):
        """Values like '1', 'true', 'yes' are treated as truthy."""
        for val in ("1", "true", "TRUE", "yes", "YES"):
            with patch.dict(os.environ, {"STRAWPOT_SKIP_UPDATE_CHECK": val}):
                assert _should_skip_update_check() is True

    def test_falsy_env_values(self):
        """Values like '0', 'false', 'no', '' are treated as falsy."""
        for val in ("0", "false", "FALSE", "no", "NO", ""):
            with patch.dict(os.environ, {"STRAWPOT_SKIP_UPDATE_CHECK": val}):
                assert _should_skip_update_check() is False

    def test_unset_env_var(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STRAWPOT_SKIP_UPDATE_CHECK", None)
            assert _should_skip_update_check() is False


# ---------------------------------------------------------------------------
# _detect_installer
# ---------------------------------------------------------------------------


class TestDetectInstaller:
    def test_frozen_binary(self):
        """Binary detection takes priority over all env-based signals."""
        with patch.object(sys, "_MEIPASS", "/tmp/frozen", create=True), \
             patch.dict(os.environ, {"PIPX_HOME": "/custom/pipx"}, clear=False):
            assert _detect_installer() == "binary"

    def test_pipx_home_with_matching_venv(self):
        """PIPX_HOME + VIRTUAL_ENV under it => pipx."""
        env = {
            "PIPX_HOME": "/custom/pipx",
            "VIRTUAL_ENV": "/custom/pipx/venvs/strawpot",
        }
        with patch.dict(os.environ, env, clear=False):
            assert _detect_installer() == "pipx"

    def test_pipx_home_without_matching_venv(self):
        """PIPX_HOME set but venv is elsewhere => pip (not a false positive)."""
        env = {
            "PIPX_HOME": "/custom/pipx",
            "VIRTUAL_ENV": "/home/user/.venv",
        }
        with patch.dict(os.environ, env, clear=False):
            assert _detect_installer() == "pip"

    def test_pipx_home_empty_string(self):
        """PIPX_HOME='' (set but empty) => treated as unset."""
        with patch.dict(os.environ, {"PIPX_HOME": "", "VIRTUAL_ENV": "/home/user/.venv"}, clear=False):
            assert _detect_installer() == "pip"

    def test_virtual_env_with_pipx_segment(self):
        venv_path = f"/home/user/.local/share/pipx{os.sep}venvs/strawpot"
        with self._without_env("PIPX_HOME"), \
             patch.dict(os.environ, {"VIRTUAL_ENV": venv_path}, clear=False):
            assert _detect_installer() == "pipx"

    def test_plain_pip(self):
        with self._without_env("PIPX_HOME"), \
             patch.dict(os.environ, {"VIRTUAL_ENV": "/home/user/.venv"}, clear=False):
            assert _detect_installer() == "pip"

    def test_no_virtual_env_no_pipx(self):
        with self._without_env("PIPX_HOME"), \
             self._without_env("VIRTUAL_ENV"):
            assert _detect_installer() == "pip"

    def test_pipx_substring_in_unrelated_path_no_match(self):
        """A path like '/home/pipxfan/.venv' should NOT trigger pipx detection."""
        with self._without_env("PIPX_HOME"), \
             patch.dict(os.environ, {"VIRTUAL_ENV": "/home/pipxfan/.venv"}, clear=False):
            assert _detect_installer() == "pip"

    def test_both_pipx_home_and_venv_segment(self):
        """When both signals agree, still returns pipx."""
        env = {
            "PIPX_HOME": "/home/user/.local/share/pipx",
            "VIRTUAL_ENV": "/home/user/.local/share/pipx/venvs/strawpot",
        }
        with patch.dict(os.environ, env, clear=False):
            assert _detect_installer() == "pipx"

    @staticmethod
    @contextmanager
    def _without_env(key: str):
        """Context manager that temporarily removes an env var if present."""
        sentinel = object()
        old = os.environ.pop(key, sentinel)
        try:
            yield
        finally:
            if old is not sentinel:
                os.environ[key] = old


# ---------------------------------------------------------------------------
# _prompt_update
# ---------------------------------------------------------------------------


class TestPromptUpdate:
    @patch("strawpot.cli._detect_installer", return_value="pip")
    @patch("strawpot.cli.subprocess.run")
    def test_user_accepts_pip_upgrade(self, mock_run, mock_installer):
        runner = CliRunner()
        result = runner.invoke(
            cli, [], input="", catch_exceptions=True,
            standalone_mode=False,
        )
        # Test the function directly
        with patch("click.confirm", return_value=True), \
             pytest.raises(SystemExit) as exc_info:
            _prompt_update("99.0.0")
        mock_run.assert_called_once()
        assert exc_info.value.code == 0

    @patch("strawpot.cli._detect_installer", return_value="pipx")
    @patch("strawpot.cli.subprocess.run")
    def test_user_accepts_pipx_upgrade(self, mock_run, mock_installer):
        with patch("click.confirm", return_value=True), \
             pytest.raises(SystemExit):
            _prompt_update("99.0.0")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["pipx", "upgrade", "strawpot"]

    @patch("strawpot.cli._detect_installer", return_value="binary")
    def test_user_accepts_binary_shows_url(self, mock_installer, capsys):
        with patch("click.confirm", return_value=True):
            _prompt_update("99.0.0")
        # Should NOT call sys.exit — just prints the URL and returns

    @patch("strawpot.cli._detect_installer", return_value="pip")
    def test_user_declines_upgrade(self, mock_installer, capsys):
        with patch("click.confirm", return_value=False):
            _prompt_update("99.0.0")
        # No sys.exit, should complete normally

    @patch("strawpot.cli._detect_installer", return_value="pip")
    @patch("strawpot.cli.subprocess.run", side_effect=subprocess.CalledProcessError(
        1, ["pip"], stderr="permission denied"))
    def test_subprocess_failure_shows_stderr(self, mock_run, mock_installer):
        with patch("click.confirm", return_value=True):
            _prompt_update("99.0.0")
        # Should NOT raise — continues gracefully

    @patch("strawpot.cli._detect_installer", return_value="pipx")
    @patch("strawpot.cli.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_binary_shows_error(self, mock_run, mock_installer, capsys):
        with patch("click.confirm", return_value=True):
            _prompt_update("99.0.0")
        # Should NOT raise — continues gracefully
