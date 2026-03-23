"""Tests for session cost rollup (_compute_session_cost)."""

from strawpot_gui.routers.sessions import _compute_session_cost


def test_cost_rollup_with_token_data():
    """Sum token data from delegate_end events."""
    events = [
        {
            "event": "delegate_start",
            "data": {"role": "implementer"},
        },
        {
            "event": "delegate_end",
            "data": {
                "role": "implementer",
                "input_tokens": 5000,
                "output_tokens": 2000,
                "cache_read_input_tokens": 1000,
                "cost_usd": 0.05,
            },
        },
        {
            "event": "delegate_end",
            "data": {
                "role": "code-reviewer",
                "input_tokens": 3000,
                "output_tokens": 1000,
                "cache_read_input_tokens": 500,
                "cost_usd": 0.03,
            },
        },
    ]
    cost = _compute_session_cost(events)
    assert cost is not None
    assert cost["total_input_tokens"] == 8000
    assert cost["total_output_tokens"] == 3000
    assert cost["total_cache_read_tokens"] == 1500
    assert cost["total_cost_usd"] == 0.08
    assert len(cost["by_role"]) == 2
    roles = {r["role"]: r for r in cost["by_role"]}
    assert roles["implementer"]["input_tokens"] == 5000
    assert roles["implementer"]["cost_usd"] == 0.05
    assert roles["code-reviewer"]["input_tokens"] == 3000
    assert roles["code-reviewer"]["cost_usd"] == 0.03


def test_cost_rollup_no_token_data():
    """Old trace events without token fields return None."""
    events = [
        {
            "event": "delegate_end",
            "data": {
                "role": "implementer",
                "exit_code": 0,
                "duration_ms": 5000,
            },
        },
    ]
    cost = _compute_session_cost(events)
    assert cost is None


def test_cost_rollup_empty_events():
    """No events at all return None."""
    assert _compute_session_cost([]) is None


def test_cost_rollup_no_delegate_end():
    """Events without delegate_end return None."""
    events = [
        {"event": "session_start", "data": {}},
        {"event": "session_end", "data": {}},
    ]
    assert _compute_session_cost(events) is None


def test_cost_rollup_mixed_with_and_without_cost():
    """Events with partial cost data — only some have cost_usd."""
    events = [
        {
            "event": "delegate_end",
            "data": {
                "role": "implementer",
                "input_tokens": 5000,
                "output_tokens": 2000,
                "cost_usd": 0.05,
            },
        },
        {
            "event": "delegate_end",
            "data": {
                "role": "reviewer",
                "input_tokens": 3000,
                "output_tokens": 1000,
                # no cost_usd
            },
        },
    ]
    cost = _compute_session_cost(events)
    assert cost is not None
    assert cost["total_input_tokens"] == 8000
    assert cost["total_cost_usd"] == 0.05  # only first had cost
    roles = {r["role"]: r for r in cost["by_role"]}
    assert roles["reviewer"]["cost_usd"] is None


def test_cost_rollup_same_role_multiple_delegations():
    """Multiple delegations to the same role are aggregated."""
    events = [
        {
            "event": "delegate_end",
            "data": {
                "role": "implementer",
                "input_tokens": 2000,
                "output_tokens": 500,
                "cost_usd": 0.02,
            },
        },
        {
            "event": "delegate_end",
            "data": {
                "role": "implementer",
                "input_tokens": 3000,
                "output_tokens": 700,
                "cost_usd": 0.03,
            },
        },
    ]
    cost = _compute_session_cost(events)
    assert cost is not None
    assert len(cost["by_role"]) == 1
    assert cost["by_role"][0]["input_tokens"] == 5000
    assert cost["by_role"][0]["output_tokens"] == 1200
    assert cost["by_role"][0]["cost_usd"] == 0.05
