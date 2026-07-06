from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from app.advisor.llm import build_chat_model
from app.config import Settings
from app.models.schemas import ConsultationTurn, HealthRecordEntry, RelevanceGateResult

SUMMARIZE_PROMPT = """\
You are closing out a chat conversation between a user and a Thai \
Traditional Medicine self-care advisor. Decide whether this conversation \
contains any health-relevant content (symptoms discussed, advice given, \
a tongue assessment, etc.) as opposed to being only greetings, small talk, \
memes, or off-topic chat.

If it has no health-relevant content, set has_health_content to false and \
leave the other fields empty.

If it does, set has_health_content to true and fill in: the user's chief \
complaint in their own words, a list of symptoms mentioned, the advice \
the advisor gave, and a concise conversation_summary (a few sentences, \
written like a doctor's chart note) that a future consultation can use \
for continuity.

Conversation transcript:
{transcript}
"""


class _SummaryDraft(BaseModel):
    """LLM-facing structured output. Deliberately excludes user_id,
    consultation_date, and tongue -- those are set deterministically by
    the caller, not invented by the model.
    """

    model_config = ConfigDict(frozen=True)

    has_health_content: bool
    chief_complaint: str = ""
    symptoms: list[str] = []
    advice_given: str = ""
    conversation_summary: str = ""


def _render_transcript(turns: list[ConsultationTurn]) -> str:
    return "\n".join(f"{turn.role}: {turn.text}" for turn in turns)


async def summarize_consultation(
    turns: list[ConsultationTurn], *, user_id: str, settings: Settings
) -> RelevanceGateResult:
    """Apply the Relevance Gate to a closed Consultation's buffered turns.

    See CONTEXT.md -> Relevance Gate and docs/adr/0002-health-record-only-memory.md.
    Note: tongue assessments made during the conversation are not yet
    threaded into the summary here -- ConsultationTurn only carries
    role/text/timestamp today. Wiring a Tongue Assessment into the closed
    entry is a follow-up once the buffer also records structured turns.
    """
    model = build_chat_model(settings.advisor_slot())
    structured_model = model.with_structured_output(_SummaryDraft)

    prompt = SUMMARIZE_PROMPT.format(transcript=_render_transcript(turns))
    draft: _SummaryDraft = await structured_model.ainvoke(prompt)

    if not draft.has_health_content:
        return RelevanceGateResult(has_health_content=False, entry=None)

    entry = HealthRecordEntry(
        user_id=user_id,
        consultation_date=datetime.now(UTC),
        chief_complaint=draft.chief_complaint,
        symptoms=draft.symptoms,
        tongue=None,
        advice_given=draft.advice_given,
        conversation_summary=draft.conversation_summary,
    )
    return RelevanceGateResult(has_health_content=True, entry=entry)
