from datetime import UTC, datetime

from langchain_core.messages import AIMessage

from app.advisor.graph import run_advisor
from app.models.schemas import ConsultationTurn


class _FakeAgent:
    """Stands in for the compiled ReAct graph: returns a canned final message."""

    def __init__(self, content: object) -> None:
        self._content = content

    async def ainvoke(self, _state: dict) -> dict:
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
