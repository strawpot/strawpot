"""Tests for strawpot.isolation.protocol."""

import tempfile

from strawpot.isolation.protocol import IsolatedEnv, Isolator, NoneIsolator


def test_isolated_env_defaults():
    path = tempfile.gettempdir()
    env = IsolatedEnv(path=path)
    assert env.path == path
    assert env.branch is None


def test_isolated_env_with_branch():
    path = tempfile.gettempdir()
    env = IsolatedEnv(path=path, branch="strawpot/run_abc")
    assert env.path == path
    assert env.branch == "strawpot/run_abc"


def test_none_isolator_create(tmp_path):
    isolator = NoneIsolator()
    base = str(tmp_path / "project")
    env = isolator.create(session_id="run_123", base_dir=base)
    assert env.path == base
    assert env.branch is None


def test_none_isolator_cleanup(tmp_path):
    isolator = NoneIsolator()
    base = str(tmp_path / "project")
    env = IsolatedEnv(path=base)
    isolator.cleanup(env, base_dir=base)  # should not raise


def test_none_isolator_satisfies_protocol():
    assert isinstance(NoneIsolator(), Isolator)


def test_incomplete_fails_protocol():
    class Incomplete:
        pass

    assert not isinstance(Incomplete(), Isolator)
