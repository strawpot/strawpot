from core.agents.types import AgentResponse, Charter, Message, ModelConfig


def test_charter_defaults():
    charter = Charter(name="charlie", role="implementer")
    assert charter.provider == "claude_session"
    assert charter.model_id is None
    assert charter.max_tokens == 8096
    assert charter.instructions == ""


def test_charter_with_model():
    charter = Charter(
        name="charlie",
        role="implementer",
        model=ModelConfig(provider="claude_subprocess", id="claude-opus-4-6"),
    )
    assert charter.provider == "claude_subprocess"
    assert charter.model_id == "claude-opus-4-6"


def test_agent_response_defaults():
    response = AgentResponse(content="hello")
    assert response.content == "hello"
    assert response.model is None
    assert response.stop_reason is None
    assert response.usage is None


def test_message_shape():
    msg: Message = {"role": "user", "content": "hello"}
    assert msg["role"] == "user"
    assert msg["content"] == "hello"
