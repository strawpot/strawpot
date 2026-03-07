"""Tests for strawpot.memory.protocol."""

from strawpot_memory.memory_protocol import (
    ContextCard,
    ControlSignal,
    DumpReceipt,
    GetResult,
    MemoryKind,
    MemoryProvider,
    RememberResult,
)


# -- MemoryKind ---------------------------------------------------------------


def test_memory_kind_values():
    assert MemoryKind.PM == "PM"
    assert MemoryKind.SM == "SM"
    assert MemoryKind.STM == "STM"
    assert MemoryKind.RM == "RM"
    assert MemoryKind.EM == "EM"


def test_memory_kind_is_str():
    assert isinstance(MemoryKind.PM, str)


# -- ContextCard ---------------------------------------------------------------


def test_context_card_defaults():
    card = ContextCard(kind=MemoryKind.SM, content="fact")
    assert card.kind is MemoryKind.SM
    assert card.content == "fact"
    assert card.source == ""


def test_context_card_with_values():
    card = ContextCard(kind=MemoryKind.PM, content="instructions", source="role:impl")
    assert card.kind is MemoryKind.PM
    assert card.content == "instructions"
    assert card.source == "role:impl"


# -- ControlSignal ------------------------------------------------------------


def test_control_signal_defaults():
    sig = ControlSignal()
    assert sig.risk_level == "normal"
    assert sig.suggested_next == ""
    assert sig.policy_flags == {}


def test_control_signal_with_values():
    sig = ControlSignal(
        risk_level="high",
        suggested_next="review",
        policy_flags={"block_deploy": "true"},
    )
    assert sig.risk_level == "high"
    assert sig.suggested_next == "review"
    assert sig.policy_flags == {"block_deploy": "true"}


# -- GetResult -----------------------------------------------------------------


def test_get_result_defaults():
    result = GetResult()
    assert result.context_cards == []
    assert result.control_signals == ControlSignal()
    assert result.context_hash == ""
    assert result.sources_used == []


def test_get_result_with_cards():
    cards = [
        ContextCard(kind=MemoryKind.PM, content="role bundle"),
        ContextCard(kind=MemoryKind.SM, content="workspace fact"),
    ]
    result = GetResult(
        context_cards=cards,
        context_hash="abc123",
        sources_used=["pm:role", "sm:facts"],
    )
    assert len(result.context_cards) == 2
    assert result.context_cards[0].kind is MemoryKind.PM
    assert result.context_hash == "abc123"
    assert result.sources_used == ["pm:role", "sm:facts"]


# -- DumpReceipt ---------------------------------------------------------------


def test_dump_receipt_defaults():
    receipt = DumpReceipt()
    assert receipt.em_event_ids == []


def test_dump_receipt_with_values():
    receipt = DumpReceipt(
        em_event_ids=["ev1", "ev2"],
    )
    assert receipt.em_event_ids == ["ev1", "ev2"]


# -- Mutable default isolation -------------------------------------------------


def test_mutable_defaults_not_shared():
    a = DumpReceipt()
    b = DumpReceipt()
    a.em_event_ids.append("x")
    assert b.em_event_ids == []


# -- MemoryProvider protocol ---------------------------------------------------


class _MinimalProvider:
    name = "test-provider"

    def get(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str,
        task: str,
        budget: int | None = None,
        parent_agent_id: str | None = None,
    ) -> GetResult:
        return GetResult()

    def dump(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str,
        task: str,
        status: str,
        output: str,
        tool_trace: str = "",
        parent_agent_id: str | None = None,
        artifacts: dict[str, str] | None = None,
    ) -> DumpReceipt:
        return DumpReceipt()

    def remember(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        content: str,
        keywords: list[str] | None = None,
        scope: str = "project",
    ) -> RememberResult:
        return RememberResult(status="accepted")


def test_provider_protocol_satisfied():
    assert isinstance(_MinimalProvider(), MemoryProvider)


def test_incomplete_fails_protocol():
    class Incomplete:
        pass

    assert not isinstance(Incomplete(), MemoryProvider)
