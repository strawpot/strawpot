"""Tests for per-session delegation cache."""

import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest

from denden.gen import denden_pb2
from strawpot.config import StrawPotConfig
from strawpot.delegation import DelegateResult
from strawpot.session import Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    overrides.setdefault("memory", "")
    return StrawPotConfig(**overrides)


def _make_session(tmp_path, **overrides):
    """Create a minimal Session for cache testing."""
    import os
    import tempfile

    from strawpot.isolation.protocol import IsolatedEnv

    role_dir = os.path.join(str(tmp_path), "roles", "test")
    os.makedirs(role_dir, exist_ok=True)
    with open(os.path.join(role_dir, "ROLE.md"), "w") as f:
        f.write("---\nname: test\ndescription: test\n---\nBody\n")

    resolved = {
        "slug": "test",
        "kind": "role",
        "version": "1.0",
        "path": role_dir,
        "source": "local",
        "dependencies": [],
    }

    wrapper = MagicMock()
    wrapper.name = "mock_wrapper"
    runtime = MagicMock()
    runtime.name = "mock_runtime"
    isolator = MagicMock()
    isolator.create.return_value = IsolatedEnv(path=tempfile.gettempdir())

    defaults = {
        "config": _make_config(),
        "wrapper": wrapper,
        "runtime": runtime,
        "isolator": isolator,
        "resolve_role": lambda slug, kind="role": resolved,
        "resolve_role_dirs": lambda s: None,
    }
    defaults.update(overrides)
    return Session(**defaults)


def _make_delegate_request(
    role="worker",
    task="Do something",
    return_format=denden_pb2.TEXT,
    agent_id="agent_abc",
    run_id="run_123",
):
    """Build a denden DenDenRequest with a delegate payload."""
    req = denden_pb2.DenDenRequest()
    req.request_id = "req_001"
    req.delegate.delegate_to = role
    req.delegate.task.text = task
    req.delegate.task.return_format = return_format
    req.trace.agent_instance_id = agent_id
    req.trace.run_id = run_id
    return req


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


class TestDelegationCacheKey:
    def test_deterministic(self):
        k1 = Session._delegation_cache_key("role", "task", "TEXT")
        k2 = Session._delegation_cache_key("role", "task", "TEXT")
        assert k1 == k2

    def test_different_role(self):
        k1 = Session._delegation_cache_key("role_a", "task", "TEXT")
        k2 = Session._delegation_cache_key("role_b", "task", "TEXT")
        assert k1 != k2

    def test_different_task(self):
        k1 = Session._delegation_cache_key("role", "task_a", "TEXT")
        k2 = Session._delegation_cache_key("role", "task_b", "TEXT")
        assert k1 != k2

    def test_different_format(self):
        k1 = Session._delegation_cache_key("role", "task", "TEXT")
        k2 = Session._delegation_cache_key("role", "task", "JSON")
        assert k1 != k2

    def test_sha256_hex(self):
        key = Session._delegation_cache_key("r", "t", "TEXT")
        assert len(key) == 64  # sha256 hex digest


# ---------------------------------------------------------------------------
# Build delegate result
# ---------------------------------------------------------------------------


class TestBuildDelegateResult:
    def test_text_output(self):
        res = Session._build_delegate_result("hello", "TEXT")
        assert res.text == "hello"

    def test_json_output(self):
        res = Session._build_delegate_result('{"key": "val"}', "JSON")
        assert res.json["key"] == "val"

    def test_json_non_dict_falls_back_to_text(self):
        res = Session._build_delegate_result("[1,2,3]", "JSON")
        assert res.text == "[1,2,3]"

    def test_empty_output(self):
        res = Session._build_delegate_result("", "TEXT")
        assert res.text == ""


# ---------------------------------------------------------------------------
# Cache integration via _handle_delegate
# ---------------------------------------------------------------------------


class TestDelegationCacheIntegration:
    """Test cache check and store via _handle_delegate."""

    def _setup_session(self, tmp_path, cache_delegations=True):
        config = _make_config(cache_delegations=cache_delegations)
        session = _make_session(tmp_path, config=config)
        # Set up minimal internal state that _handle_delegate expects
        session._tracer = MagicMock()
        session._tracer.delegate_start.return_value = "span_001"
        session._session_span_id = "session_span"
        session._agent_info = {
            "agent_abc": {"role": "parent_role", "parent": None}
        }
        session._agent_spans = {"agent_abc": "span_parent"}
        session._env = MagicMock()
        session._env.path = str(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_123"
        session._denden_addr = "127.0.0.1:9700"
        session._memory_provider = None
        session._files_dirs = []
        # Ensure session_dir exists for handle_delegate
        import os
        session_dir = os.path.join(str(tmp_path), ".strawpot", "sessions", "run_123")
        os.makedirs(session_dir, exist_ok=True)
        return session

    @patch("strawpot.session.handle_delegate")
    def test_cache_hit_skips_handle_delegate(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path)
        mock_hd.return_value = DelegateResult(output="result text", exit_code=0)

        req = _make_delegate_request()

        # First call — cache miss, calls handle_delegate
        resp1 = session._handle_delegate(req)
        assert mock_hd.call_count == 1
        assert resp1.status == denden_pb2.OK

        # Second call — cache hit, does NOT call handle_delegate
        resp2 = session._handle_delegate(req)
        assert mock_hd.call_count == 1  # still 1
        assert resp2.status == denden_pb2.OK
        assert resp2.delegate_result.text == "result text"

    @patch("strawpot.session.handle_delegate")
    def test_cache_miss_on_different_role(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        req1 = _make_delegate_request(role="worker_a")
        req2 = _make_delegate_request(role="worker_b")

        session._handle_delegate(req1)
        session._handle_delegate(req2)
        assert mock_hd.call_count == 2

    @patch("strawpot.session.handle_delegate")
    def test_cache_miss_on_different_task(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        req1 = _make_delegate_request(task="task A")
        req2 = _make_delegate_request(task="task B")

        session._handle_delegate(req1)
        session._handle_delegate(req2)
        assert mock_hd.call_count == 2

    @patch("strawpot.session.handle_delegate")
    def test_failed_result_not_cached(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path)
        mock_hd.return_value = DelegateResult(output="error", exit_code=1)

        req = _make_delegate_request()

        session._handle_delegate(req)
        session._handle_delegate(req)
        # Both calls go through handle_delegate (failure not cached)
        assert mock_hd.call_count == 2

    @patch("strawpot.session.handle_delegate")
    def test_empty_output_not_cached(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path)
        mock_hd.return_value = DelegateResult(output="", exit_code=0)

        req = _make_delegate_request()

        session._handle_delegate(req)
        session._handle_delegate(req)
        # Empty output is not worth caching
        assert mock_hd.call_count == 2

    @patch("strawpot.session.handle_delegate")
    def test_cache_disabled_skips_caching(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path, cache_delegations=False)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        req = _make_delegate_request()

        session._handle_delegate(req)
        session._handle_delegate(req)
        assert mock_hd.call_count == 2

    @patch("strawpot.session.handle_delegate")
    def test_cache_hit_emits_trace_events(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        req = _make_delegate_request()

        # First call — normal delegation
        session._handle_delegate(req)
        # Reset tracer mock to only track cache-hit events
        session._tracer.delegate_start.reset_mock()
        session._tracer.delegate_end.reset_mock()

        # Second call — cache hit
        session._handle_delegate(req)

        # Verify trace events emitted with cache_hit=True
        session._tracer.delegate_start.assert_called_once()
        start_kwargs = session._tracer.delegate_start.call_args.kwargs
        assert start_kwargs["cache_hit"] is True
        assert start_kwargs["role"] == "worker"

        session._tracer.delegate_end.assert_called_once()
        end_kwargs = session._tracer.delegate_end.call_args.kwargs
        assert end_kwargs["cache_hit"] is True
        assert end_kwargs["duration_ms"] == 0
        assert end_kwargs["output"] == "ok"

    @patch("strawpot.session.handle_delegate")
    def test_cache_hit_json_format(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path)
        mock_hd.return_value = DelegateResult(
            output='{"key": "value"}', exit_code=0
        )

        req = _make_delegate_request(return_format=denden_pb2.JSON)

        # First call
        session._handle_delegate(req)
        # Second call — cache hit
        resp = session._handle_delegate(req)

        assert resp.delegate_result.json["key"] == "value"
        assert mock_hd.call_count == 1


# ---------------------------------------------------------------------------
# Cache eviction policy
# ---------------------------------------------------------------------------


class TestDelegationCacheEviction:
    """Test max_entries and TTL eviction."""

    def _setup_session(self, tmp_path, **config_overrides):
        config_overrides.setdefault("cache_delegations", True)
        config = _make_config(**config_overrides)
        session = _make_session(tmp_path, config=config)
        session._tracer = MagicMock()
        session._tracer.delegate_start.return_value = "span_001"
        session._session_span_id = "session_span"
        session._agent_info = {
            "agent_abc": {"role": "parent_role", "parent": None}
        }
        session._agent_spans = {"agent_abc": "span_parent"}
        session._env = MagicMock()
        session._env.path = str(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_123"
        session._denden_addr = "127.0.0.1:9700"
        session._memory_provider = None
        session._files_dirs = []
        import os
        session_dir = os.path.join(str(tmp_path), ".strawpot", "sessions", "run_123")
        os.makedirs(session_dir, exist_ok=True)
        return session

    @patch("strawpot.session.handle_delegate")
    def test_max_entries_evicts_oldest(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path, cache_max_entries=2)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        req_a = _make_delegate_request(task="task_a")
        req_b = _make_delegate_request(task="task_b")
        req_c = _make_delegate_request(task="task_c")

        session._handle_delegate(req_a)  # cache: [a]
        session._handle_delegate(req_b)  # cache: [a, b]
        session._handle_delegate(req_c)  # cache: [b, c] — a evicted

        assert len(session._delegation_cache) == 2

        # a should be evicted — calling it again triggers handle_delegate
        call_count_before = mock_hd.call_count
        session._handle_delegate(req_a)
        assert mock_hd.call_count == call_count_before + 1  # cache miss

        # c should still be cached
        call_count_before = mock_hd.call_count
        session._handle_delegate(req_c)
        assert mock_hd.call_count == call_count_before  # cache hit

        # cache never exceeds max_entries
        assert len(session._delegation_cache) == 2

    @patch("strawpot.session.handle_delegate")
    def test_ttl_expires_entry(self, mock_hd, tmp_path, monkeypatch):
        session = self._setup_session(tmp_path, cache_ttl_seconds=60)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        fake_time = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_time)

        req = _make_delegate_request()
        session._handle_delegate(req)  # cached at t=1000
        assert mock_hd.call_count == 1

        # Within TTL — cache hit
        fake_time = 1050.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_time)
        session._handle_delegate(req)
        assert mock_hd.call_count == 1  # still cached

        # Beyond TTL — cache miss
        fake_time = 1061.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_time)
        session._handle_delegate(req)
        assert mock_hd.call_count == 2  # re-delegated

    @patch("strawpot.session.handle_delegate")
    def test_zero_max_entries_means_unlimited(self, mock_hd, tmp_path):
        session = self._setup_session(tmp_path, cache_max_entries=0)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        for i in range(20):
            req = _make_delegate_request(task=f"task_{i}")
            session._handle_delegate(req)

        assert len(session._delegation_cache) == 20

    @patch("strawpot.session.handle_delegate")
    def test_zero_ttl_means_unlimited(self, mock_hd, tmp_path, monkeypatch):
        session = self._setup_session(tmp_path, cache_ttl_seconds=0)
        mock_hd.return_value = DelegateResult(output="ok", exit_code=0)

        fake_time = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_time)

        req = _make_delegate_request()
        session._handle_delegate(req)

        # Far in the future — still cached
        fake_time = 999999.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_time)
        session._handle_delegate(req)
        assert mock_hd.call_count == 1  # cache hit
