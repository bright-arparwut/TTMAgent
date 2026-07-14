from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage

from app.advisor.graph import run_advisor
from app.models.schemas import ConsultationTurn


class _FakeAgent:
    """Stands in for the compiled ReAct graph: returns a canned final message."""

    def __init__(self, content: object) -> None:
        self._content = content
        self.invoked_state: dict | None = None

    async def ainvoke(self, state: dict) -> dict:
        self.invoked_state = state
        return {"messages": [AIMessage(content=self._content)]}


async def test_run_advisor_returns_plain_string_content_unchanged():
    fake = _FakeAgent("สวัสดีค่ะ มีอะไรให้ช่วยคะ")
    reply = await run_advisor(
        fake,
        user_message="ปวดหลัง",
        retrieved_passages=[],
        recent_records_summary="",
    )
    assert reply == "สวัสดีค่ะ มีอะไรให้ช่วยคะ"


async def test_run_advisor_flattens_gemini_thinking_content_blocks_to_string():
    """Gemini with thinking enabled returns .content as a *list* of content
    blocks (a thought-signature block plus visible text), not a str. The reply
    must still be a plain string so it can land in ConsultationTurn.text."""
    content = [
        {"type": "text", "text": "สวัสดีค่ะ ", "extras": {"signature": "W2L4Afejf93UQpUXfyU="}},
        {"type": "text", "text": "มีอะไรให้ช่วยดูแลคะ"},
    ]
    fake = _FakeAgent(content)

    reply = await run_advisor(
        fake,
        user_message="ปวดหลัง",
        retrieved_passages=[],
        recent_records_summary="",
    )

    assert isinstance(reply, str)
    assert reply == "สวัสดีค่ะ มีอะไรให้ช่วยดูแลคะ"
    # The exact user symptom: this reply must be accepted by ConsultationTurn.
    ConsultationTurn(role="advisor", text=reply, timestamp=datetime.now(UTC))


def _turn(role: str, text: str) -> ConsultationTurn:
    return ConsultationTurn(role=role, text=text, timestamp=datetime.now(UTC))


async def test_run_advisor_replays_history_as_role_tagged_messages():
    """Working Buffer replay (ADR 0005): prior turns become HumanMessage /
    AIMessage history ahead of the current message."""
    fake = _FakeAgent("ตอบ")
    history = [
        _turn("user", "ปวดหัวมาก"),
        _turn("advisor", "ปวดหัวมานานแค่ไหนคะ"),
    ]

    await run_advisor(
        fake,
        user_message="ประมาณสามวันค่ะ",
        retrieved_passages=[],
        recent_records_summary="",
        history=history,
    )

    messages = fake.invoked_state["messages"]
    assert len(messages) == 3
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "ปวดหัวมาก"
    assert isinstance(messages[1], AIMessage)
    assert messages[1].content == "ปวดหัวมานานแค่ไหนคะ"
    assert isinstance(messages[2], HumanMessage)
    # The current message carries the ongoing-consultation marker; history
    # replay itself is what this test pins down.
    assert "ประมาณสามวันค่ะ" in messages[2].content


async def test_run_advisor_attaches_context_block_to_current_message_only():
    """The retrieved context block rides on the latest message; replayed
    turns stay raw stored text (ADR 0005)."""
    fake = _FakeAgent("ตอบ")
    history = [_turn("user", "ปวดหัวมาก")]

    await run_advisor(
        fake,
        user_message="ประมาณสามวันค่ะ",
        retrieved_passages=["ตำราแพทย์แผนไทยว่าด้วยธาตุ"],
        recent_records_summary="",
        history=history,
    )

    messages = fake.invoked_state["messages"]
    assert messages[0].content == "ปวดหัวมาก"  # no context block on history
    assert "ตำราแพทย์แผนไทยว่าด้วยธาตุ" in messages[-1].content
    assert "ประมาณสามวันค่ะ" in messages[-1].content


async def test_run_advisor_marks_ongoing_consultation_when_history_exists():
    """The no-greeting signal must be deterministic: the spine knows whether
    prior turns exist, so the current message carries an explicit ongoing-
    consultation marker instead of asking the model to infer it."""
    fake = _FakeAgent("ตอบ")
    history = [_turn("user", "ปวดหัวมาก")]

    await run_advisor(
        fake,
        user_message="ประมาณสามวันค่ะ",
        retrieved_passages=[],
        recent_records_summary="",
        history=history,
    )

    assert "[Ongoing Consultation" in fake.invoked_state["messages"][-1].content


async def test_run_advisor_without_history_sends_single_message():
    fake = _FakeAgent("ตอบ")

    await run_advisor(
        fake,
        user_message="สวัสดีค่ะ",
        retrieved_passages=[],
        recent_records_summary="",
    )

    messages = fake.invoked_state["messages"]
    assert len(messages) == 1
    assert messages[0].content == "สวัสดีค่ะ"
