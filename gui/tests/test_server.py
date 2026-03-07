"""Tests for server module — single-instance check and entry point."""

import socket
from unittest.mock import MagicMock, patch

from strawpot_gui.server import _is_strawpot_gui, _port_in_use


class TestPortInUse:
    def test_free_port(self):
        # Use port 0 to get a random free port, then check it
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            _, port = s.getsockname()
        # Port is now unbound
        assert _port_in_use("127.0.0.1", port) is False

    def test_bound_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            _, port = s.getsockname()
            assert _port_in_use("127.0.0.1", port) is True


class TestIsStrawpotGui:
    @patch("strawpot_gui.server.urllib.request.urlopen")
    def test_returns_true_for_health_ok(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        assert _is_strawpot_gui("127.0.0.1", 8741) is True

    @patch("strawpot_gui.server.urllib.request.urlopen")
    def test_returns_false_for_other_service(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "not_strawpot"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        assert _is_strawpot_gui("127.0.0.1", 8741) is False

    def test_returns_false_on_connection_error(self):
        assert _is_strawpot_gui("127.0.0.1", 1) is False


class TestMain:
    @patch("strawpot_gui.server.webbrowser.open")
    @patch("strawpot_gui.server._is_strawpot_gui", return_value=True)
    @patch("strawpot_gui.server._port_in_use", return_value=True)
    def test_existing_instance_opens_browser(self, mock_port, mock_gui, mock_browser):
        from strawpot_gui.server import main

        main(port=8741)
        mock_browser.assert_called_once_with("http://127.0.0.1:8741")

    @patch("strawpot_gui.server._is_strawpot_gui", return_value=False)
    @patch("strawpot_gui.server._port_in_use", return_value=True)
    def test_port_in_use_by_other_exits(self, mock_port, mock_gui):
        import pytest

        from strawpot_gui.server import main

        with pytest.raises(SystemExit) as exc_info:
            main(port=8741)
        assert exc_info.value.code == 1
