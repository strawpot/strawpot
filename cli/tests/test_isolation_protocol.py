"""Tests for strawpot.isolation.protocol."""

from strawpot.isolation.protocol import IsolatedEnv, Isolator, NoneIsolator


def test_isolated_env_defaults():
    env = IsolatedEnv(path="/tmp/work")
    assert env.path == "/tmp/work"
    assert env.branch is None


def test_isolated_env_with_branch():
    env = IsolatedEnv(path="/tmp/work", branch="strawpot/run_abc")
    assert env.path == "/tmp/work"
    assert env.branch == "strawpot/run_abc"


def test_none_isolator_create():
    isolator = NoneIsolator()
    env = isolator.create(session_id="run_123", base_dir="/home/user/project")
    assert env.path == "/home/user/project"
    assert env.branch is None


def test_none_isolator_cleanup():
    isolator = NoneIsolator()
    env = IsolatedEnv(path="/home/user/project")
    isolator.cleanup(env, base_dir="/home/user/project")  # should not raise


def test_none_isolator_satisfies_protocol():
    assert isinstance(NoneIsolator(), Isolator)


def test_incomplete_fails_protocol():
    class Incomplete:
        pass

    assert not isinstance(Incomplete(), Isolator)
