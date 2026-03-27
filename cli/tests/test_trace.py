"""Tests for strawpot.trace."""

import json
import os
import stat
from pathlib import Path

import pytest

from strawpot.trace import TraceEvent, Tracer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_events(session_dir):
    """Read all JSONL events from trace.jsonl."""
    path = os.path.join(session_dir, "trace.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _make_tracer(tmp_path, trace_id="run_test123"):
    session_dir = str(tmp_path / "session")
    os.makedirs(session_dir, exist_ok=True)
    return Tracer(session_dir, trace_id), session_dir


# ---------------------------------------------------------------------------
# TraceEvent dataclass
# ---------------------------------------------------------------------------


class TestTraceEvent:
    def test_fields(self):
        te = TraceEvent(
            ts="2026-01-01T00:00:00+00:00",
            event="test",
            trace_id="t1",
            span_id="s1",
            parent_span="s0",
            data={"key": "val"},
        )
        assert te.event == "test"
        assert te.parent_span == "s0"
        assert te.data == {"key": "val"}

    def test_parent_span_defaults_none(self):
        te = TraceEvent(ts="", event="e", trace_id="t", span_id="s")
        assert te.parent_span is None
        assert te.data == {}


# ---------------------------------------------------------------------------
# Tracer init
# ---------------------------------------------------------------------------


class TestTracerInit:
    def test_creates_artifacts_dir(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        assert os.path.isdir(os.path.join(session_dir, "artifacts"))

    def test_trace_jsonl_created_on_first_emit(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        trace_path = os.path.join(session_dir, "trace.jsonl")
        assert not os.path.exists(trace_path)
        tracer.emit("test_event", "span1")
        assert os.path.isfile(trace_path)


# ---------------------------------------------------------------------------
# store_artifact
# ---------------------------------------------------------------------------


class TestStoreArtifact:
    def test_stores_content_by_hash(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        ref = tracer.store_artifact("hello world")
        assert ref is not None
        artifact_path = os.path.join(session_dir, "artifacts", ref)
        assert os.path.isfile(artifact_path)
        with open(artifact_path, encoding="utf-8") as f:
            assert f.read() == "hello world"

    def test_returns_hash_ref(self, tmp_path):
        tracer, _ = _make_tracer(tmp_path)
        ref = tracer.store_artifact("test content")
        assert isinstance(ref, str)
        assert len(ref) == 12

    def test_empty_content_returns_none(self, tmp_path):
        tracer, _ = _make_tracer(tmp_path)
        assert tracer.store_artifact("") is None

    def test_deduplication(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        ref1 = tracer.store_artifact("same content")
        ref2 = tracer.store_artifact("same content")
        assert ref1 == ref2
        artifacts = os.listdir(os.path.join(session_dir, "artifacts"))
        assert len(artifacts) == 1

    def test_different_content_different_hash(self, tmp_path):
        tracer, _ = _make_tracer(tmp_path)
        ref1 = tracer.store_artifact("content A")
        ref2 = tracer.store_artifact("content B")
        assert ref1 != ref2


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


class TestEmit:
    def test_writes_jsonl_line(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.emit("test_event", "span1", key="value")
        events = _read_events(session_dir)
        assert len(events) == 1
        assert events[0]["event"] == "test_event"
        assert events[0]["span_id"] == "span1"
        assert events[0]["data"]["key"] == "value"

    def test_multiple_events_appended(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.emit("e1", "s1")
        tracer.emit("e2", "s2")
        tracer.emit("e3", "s3")
        events = _read_events(session_dir)
        assert len(events) == 3
        assert [e["event"] for e in events] == ["e1", "e2", "e3"]

    def test_event_has_iso_timestamp(self, tmp_path):
        from datetime import datetime

        tracer, session_dir = _make_tracer(tmp_path)
        tracer.emit("e", "s")
        events = _read_events(session_dir)
        ts = events[0]["ts"]
        # Should parse without error
        datetime.fromisoformat(ts)

    def test_event_has_trace_id(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path, trace_id="run_abc")
        tracer.emit("e", "s")
        events = _read_events(session_dir)
        assert events[0]["trace_id"] == "run_abc"

    def test_parent_span_can_be_none(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.emit("e", "s")
        events = _read_events(session_dir)
        assert events[0]["parent_span"] is None

    def test_parent_span_set(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.emit("e", "s", parent_span="p1")
        events = _read_events(session_dir)
        assert events[0]["parent_span"] == "p1"


# ---------------------------------------------------------------------------
# Session events
# ---------------------------------------------------------------------------


class TestSessionEvents:
    def test_session_start_returns_span_id(self, tmp_path):
        tracer, _ = _make_tracer(tmp_path)
        span_id = tracer.session_start(
            run_id="run_1", role="orchestrator",
            runtime="strawpot-claude-code", isolation="none",
        )
        assert isinstance(span_id, str)
        assert len(span_id) == 12

    def test_session_start_event_written(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.session_start(
            run_id="run_1", role="orchestrator",
            runtime="strawpot-claude-code", isolation="worktree",
            task="Fix the bug",
        )
        events = _read_events(session_dir)
        assert len(events) == 1
        assert events[0]["event"] == "session_start"
        assert events[0]["data"]["role"] == "orchestrator"
        assert events[0]["data"]["isolation"] == "worktree"
        assert events[0]["data"]["task_ref"] is not None
        # Verify artifact was stored
        artifact_path = Path(session_dir) / "artifacts" / events[0]["data"]["task_ref"]
        assert artifact_path.read_text() == "Fix the bug"

    def test_session_end_event_written(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        span_id = tracer.session_start(
            run_id="r", role="o", runtime="r", isolation="n",
        )
        tracer.session_end(
            span_id=span_id, merge_action="local", duration_ms=5000,
            output="Task completed successfully.",
        )
        events = _read_events(session_dir)
        assert events[1]["event"] == "session_end"
        assert events[1]["data"]["duration_ms"] == 5000
        assert events[1]["data"]["merge_action"] == "local"
        assert events[1]["data"]["output_ref"] is not None
        artifact_path = Path(session_dir) / "artifacts" / events[1]["data"]["output_ref"]
        assert artifact_path.read_text() == "Task completed successfully."


# ---------------------------------------------------------------------------
# Delegate events
# ---------------------------------------------------------------------------


class TestDelegateEvents:
    def test_delegate_start_stores_context_artifact(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        span_id = tracer.delegate_start(
            role="reviewer", parent_span="root",
            context="Review this code please.",
            session_id="run_abc", parent_agent_id="agent_000",
        )
        assert isinstance(span_id, str)
        events = _read_events(session_dir)
        assert events[0]["event"] == "delegate_start"
        assert events[0]["data"]["session_id"] == "run_abc"
        assert events[0]["data"]["parent_agent_id"] == "agent_000"
        ref = events[0]["data"]["context_ref"]
        assert ref is not None
        artifact_path = os.path.join(session_dir, "artifacts", ref)
        with open(artifact_path, encoding="utf-8") as f:
            assert f.read() == "Review this code please."

    def test_delegate_start_records_depth(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.delegate_start(
            role="reviewer", parent_span="root",
            context="review", depth=2,
        )
        events = _read_events(session_dir)
        assert events[0]["data"]["depth"] == 2

    def test_delegate_end_event(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.delegate_end(
            span_id="s1", exit_code=0, duration_ms=1234,
            output="task output here",
            role="reviewer", session_id="run_abc", agent_id="agent_123",
        )
        events = _read_events(session_dir)
        assert events[0]["event"] == "delegate_end"
        assert events[0]["data"]["exit_code"] == 0
        assert events[0]["data"]["duration_ms"] == 1234
        assert events[0]["data"]["role"] == "reviewer"
        assert events[0]["data"]["session_id"] == "run_abc"
        assert events[0]["data"]["agent_id"] == "agent_123"
        ref = events[0]["data"]["output_ref"]
        assert ref is not None
        artifact_path = os.path.join(session_dir, "artifacts", ref)
        with open(artifact_path, encoding="utf-8") as f:
            assert f.read() == "task output here"

    def test_delegate_denied_event(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.delegate_denied(
            role="admin", parent_span="root", reason="DENY_ROLE_NOT_ALLOWED",
        )
        events = _read_events(session_dir)
        assert events[0]["event"] == "delegate_denied"
        assert events[0]["data"]["role"] == "admin"
        assert events[0]["data"]["reason"] == "DENY_ROLE_NOT_ALLOWED"

    def test_delegate_denied_records_depth(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.delegate_denied(
            role="admin", parent_span="root",
            reason="DENY_DEPTH_LIMIT", depth=3,
        )
        events = _read_events(session_dir)
        assert events[0]["data"]["depth"] == 3


# ---------------------------------------------------------------------------
# Memory events
# ---------------------------------------------------------------------------


class TestMemoryEvents:
    def test_memory_get_stores_cards_artifact(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.memory_get(
            span_id="s1", provider="semantic",
            session_id="run_abc", agent_id="agent_123",
            role="implementer", behavior_ref="You are an implementer.",
            task="write tests",
            cards=["card1", "card2"], card_count=2,
            parent_agent_id="agent_000",
        )
        events = _read_events(session_dir)
        assert events[0]["event"] == "memory_get"
        assert events[0]["data"]["card_count"] == 2
        assert events[0]["data"]["session_id"] == "run_abc"
        assert events[0]["data"]["agent_id"] == "agent_123"
        assert events[0]["data"]["role"] == "implementer"
        assert events[0]["data"]["behavior_ref"] is not None
        assert events[0]["data"]["task_ref"] is not None
        assert events[0]["data"]["parent_agent_id"] == "agent_000"
        ref = events[0]["data"]["cards_ref"]
        assert ref is not None

    def test_memory_get_empty_cards(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.memory_get(
            span_id="s1", provider="noop",
            session_id="run_x", agent_id="agent_x", role="worker",
            cards=[], card_count=0,
        )
        events = _read_events(session_dir)
        assert events[0]["data"]["cards_ref"] is None

    def test_memory_dump_stores_all_arguments(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.memory_dump(
            span_id="s1", provider="semantic",
            session_id="run_abc", agent_id="agent_123",
            role="implementer", behavior_ref="You are an implementer.",
            task="write tests", status="success",
            output="agent output text", parent_agent_id="agent_000",
        )
        events = _read_events(session_dir)
        assert events[0]["event"] == "memory_dump"
        data = events[0]["data"]
        assert data["provider"] == "semantic"
        assert data["session_id"] == "run_abc"
        assert data["agent_id"] == "agent_123"
        assert data["role"] == "implementer"
        assert data["status"] == "success"
        assert data["parent_agent_id"] == "agent_000"
        # behavior_ref, task_ref, output_ref stored as artifacts
        assert data["behavior_ref"] is not None
        assert data["task_ref"] is not None
        assert data["output_ref"] is not None
        artifact_path = os.path.join(session_dir, "artifacts", data["output_ref"])
        with open(artifact_path, encoding="utf-8") as f:
            assert f.read() == "agent output text"

    def test_memory_recall_stores_all_arguments(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        results = [
            {"content": "memory card 1", "score": 0.9, "scope": "project"},
            {"content": "memory card 2", "score": 0.7, "scope": "global"},
        ]
        tracer.memory_recall(
            span_id="s1", provider="dial",
            session_id="run_abc", agent_id="agent_123",
            role="implementer", query="testing framework",
            scope="project", result_count=2,
            results=results,
            parent_agent_id="agent_000",
        )
        events = _read_events(session_dir)
        assert events[0]["event"] == "memory_recall"
        data = events[0]["data"]
        assert data["provider"] == "dial"
        assert data["session_id"] == "run_abc"
        assert data["agent_id"] == "agent_123"
        assert data["role"] == "implementer"
        assert data["query"] == "testing framework"
        assert data["scope"] == "project"
        assert data["result_count"] == 2
        assert data["parent_agent_id"] == "agent_000"
        # results_ref should point to stored artifact
        assert data["results_ref"] is not None
        artifact_path = os.path.join(session_dir, "artifacts", data["results_ref"])
        assert os.path.isfile(artifact_path)
        import json
        with open(artifact_path, encoding="utf-8") as f:
            stored = json.loads(f.read())
        assert len(stored) == 2
        assert stored[0]["content"] == "memory card 1"

    def test_memory_recall_defaults(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.memory_recall(
            span_id="s1", provider="dial",
            session_id="run_x", agent_id="agent_x", role="worker",
        )
        events = _read_events(session_dir)
        data = events[0]["data"]
        assert data["query"] == ""
        assert data["scope"] == ""
        assert data["result_count"] == 0
        assert data["results_ref"] is None


# ---------------------------------------------------------------------------
# Agent events
# ---------------------------------------------------------------------------


class TestAgentEvents:
    def test_agent_spawn_event(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.agent_spawn(
            span_id="s1", agent_id="agent_abc",
            role="ai-ceo", runtime="strawpot-claude-code", pid=12345,
            working_dir="/project",
            agent_workspace_dir="/session/agents/agent_abc",
            skills_dirs=["/session/roles/ai-ceo/skills"],
            roles_dirs=["/session/roles/ai-ceo/roles"],
            files_dirs=["/project/.strawpot/files"],
            task="build the app",
            context="You are the CEO agent.",
        )
        events = _read_events(session_dir)
        assert events[0]["event"] == "agent_spawn"
        data = events[0]["data"]
        assert data["agent_id"] == "agent_abc"
        assert data["role"] == "ai-ceo"
        assert data["pid"] == 12345
        assert data["working_dir"] == "/project"
        assert data["agent_workspace_dir"] == "/session/agents/agent_abc"
        assert data["skills_dirs"] == ["/session/roles/ai-ceo/skills"]
        assert data["roles_dirs"] == ["/session/roles/ai-ceo/roles"]
        assert data["files_dirs"] == ["/project/.strawpot/files"]
        assert data["task_ref"] is not None
        assert data["context_ref"] is not None
        artifact_path = Path(session_dir) / "artifacts" / data["context_ref"]
        assert artifact_path.read_text() == "You are the CEO agent."
        task_path = Path(session_dir) / "artifacts" / data["task_ref"]
        assert task_path.read_text() == "build the app"

    def test_agent_spawn_records_depth(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.agent_spawn(
            span_id="s1", agent_id="agent_abc",
            role="implementer", runtime="strawpot-claude-code", pid=111,
            depth=1,
        )
        events = _read_events(session_dir)
        assert events[0]["data"]["depth"] == 1

    def test_agent_end_stores_output_artifact(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.agent_end(
            span_id="s1", exit_code=0,
            output="task completed successfully", duration_ms=9876,
            agent_id="agent_123", role="implementer", session_id="run_abc",
        )
        events = _read_events(session_dir)
        assert events[0]["event"] == "agent_end"
        assert events[0]["data"]["exit_code"] == 0
        assert events[0]["data"]["duration_ms"] == 9876
        assert events[0]["data"]["agent_id"] == "agent_123"
        assert events[0]["data"]["role"] == "implementer"
        assert events[0]["data"]["session_id"] == "run_abc"
        ref = events[0]["data"]["output_ref"]
        assert ref is not None
        artifact_path = os.path.join(session_dir, "artifacts", ref)
        with open(artifact_path, encoding="utf-8") as f:
            assert f.read() == "task completed successfully"


# ---------------------------------------------------------------------------
# Ask_user events
# ---------------------------------------------------------------------------


class TestAskUserEvents:
    def test_ask_user_start_returns_span_id(self, tmp_path):
        tracer, _ = _make_tracer(tmp_path)
        span_id = tracer.ask_user_start(
            parent_span="root",
            request_id="req_abc123",
            question="Should I proceed?",
        )
        assert isinstance(span_id, str)
        assert len(span_id) == 12

    def test_ask_user_start_stores_question_artifact(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        question = "Choose an option\n\nChoices: yes, no\n\nDefault: yes"
        tracer.ask_user_start(
            parent_span="root",
            request_id="req_abc123",
            question=question,
            agent_id="agent_123",
            role="implementer",
            session_id="run_abc",
        )
        events = _read_events(session_dir)
        assert len(events) == 1
        assert events[0]["event"] == "ask_user_start"
        assert events[0]["parent_span"] == "root"
        data = events[0]["data"]
        assert data["request_id"] == "req_abc123"
        assert data["question_ref"] is not None
        assert data["agent_id"] == "agent_123"
        assert data["role"] == "implementer"
        assert data["session_id"] == "run_abc"
        # Verify artifact content
        artifact_path = os.path.join(session_dir, "artifacts", data["question_ref"])
        with open(artifact_path, encoding="utf-8") as f:
            assert f.read() == question

    def test_ask_user_end_stores_answer_artifact(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.ask_user_end(
            span_id="s1",
            request_id="req_abc123",
            answer="yes",
            duration_ms=5000,
            agent_id="agent_123",
            role="implementer",
            session_id="run_abc",
        )
        events = _read_events(session_dir)
        assert len(events) == 1
        assert events[0]["event"] == "ask_user_end"
        assert events[0]["span_id"] == "s1"
        data = events[0]["data"]
        assert data["request_id"] == "req_abc123"
        assert data["answer_ref"] is not None
        assert data["duration_ms"] == 5000
        assert data["agent_id"] == "agent_123"
        assert data["role"] == "implementer"
        assert data["session_id"] == "run_abc"
        artifact_path = os.path.join(session_dir, "artifacts", data["answer_ref"])
        with open(artifact_path, encoding="utf-8") as f:
            assert f.read() == "yes"


# ---------------------------------------------------------------------------
# I/O error resilience
# ---------------------------------------------------------------------------


class TestIOResilience:
    @pytest.mark.skipif(
        os.getuid() == 0, reason="root can write to read-only dirs"
    )
    def test_emit_on_readonly_dir_does_not_raise(self, tmp_path):
        session_dir = str(tmp_path / "readonly_session")
        os.makedirs(session_dir)
        tracer = Tracer(session_dir, "run_x")
        # Make session dir read-only
        os.chmod(session_dir, stat.S_IRUSR | stat.S_IXUSR)
        try:
            # Should not raise
            tracer.emit("test", "span1")
        finally:
            # Restore permissions for cleanup
            os.chmod(session_dir, stat.S_IRWXU)


# ---------------------------------------------------------------------------
# Cancel trace events
# ---------------------------------------------------------------------------


class TestCancelTraceEvents:
    def test_agent_cancel_start(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.agent_cancel_start(
            span_id="span_1",
            agent_id="agent_a",
            reason="user",
            force=False,
            descendants=["agent_b", "agent_c"],
        )
        events = _read_events(session_dir)
        assert len(events) == 1
        e = events[0]
        assert e["event"] == "agent_cancel_start"
        assert e["span_id"] == "span_1"
        assert e["data"]["agent_id"] == "agent_a"
        assert e["data"]["reason"] == "user"
        assert e["data"]["force"] is False
        assert e["data"]["descendants"] == ["agent_b", "agent_c"]
        assert e["data"]["descendant_count"] == 2

    def test_agent_cancel_complete(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.agent_cancel_complete(
            span_id="span_1",
            agent_id="agent_a",
            cancelled_agents=["agent_c", "agent_b", "agent_a"],
            duration_ms=1500,
        )
        events = _read_events(session_dir)
        assert len(events) == 1
        e = events[0]
        assert e["event"] == "agent_cancel_complete"
        assert e["data"]["agent_id"] == "agent_a"
        assert e["data"]["cancelled_agents"] == ["agent_c", "agent_b", "agent_a"]
        assert e["data"]["cancelled_count"] == 3
        assert e["data"]["duration_ms"] == 1500

    def test_cancel_start_empty_descendants(self, tmp_path):
        tracer, session_dir = _make_tracer(tmp_path)
        tracer.agent_cancel_start(
            span_id="span_1",
            agent_id="agent_a",
            reason="timeout",
            force=True,
            descendants=[],
        )
        events = _read_events(session_dir)
        assert events[0]["data"]["descendant_count"] == 0
        assert events[0]["data"]["force"] is True
