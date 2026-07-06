from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


def _utc_when_naive(value: datetime) -> datetime:
    """MongoDB returns naive datetimes (the client is not tz_aware);
    this system only ever stores UTC, so naive means UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ConsultationTurn(BaseModel):
    """One raw message in the working buffer. Never persisted past Consultation close."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "advisor"]
    text: str
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _assume_utc_when_naive(cls, value: datetime) -> datetime:
        return _utc_when_naive(value)


class TongueDescription(BaseModel):
    """Structured output of the Vision Describer for one tongue photo.

    Fields are a placeholder pending the TTM textbook's tongue-inspection
    categories (see CONTEXT.md -> Tongue Description). Extend/replace the
    category fields once the book schema is finalized; keep `notes` and
    `quality` regardless, since they are the escape hatch and the retake
    trigger respectively.
    """

    model_config = ConfigDict(frozen=True)

    body_color: str
    body_shape: str
    coating_color: str
    coating_thickness: str
    moisture: str
    cracks: bool
    teeth_marks: bool
    notes: str = ""
    quality: Literal["clear", "blurry", "partial", "poor_lighting"]


class TongueAssessment(BaseModel):
    """The Advisor Model's TTM-grounded interpretation of a Tongue Description."""

    model_config = ConfigDict(frozen=True)

    description: TongueDescription
    assessment_text: str


class HealthRecordEntry(BaseModel):
    """One closed, clinically-relevant Consultation, written once at close time.

    Written deterministically by the Relevance Gate summarizer -- never by an
    LLM tool call. See docs/adr/0002-health-record-only-memory.md.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    consultation_date: datetime
    chief_complaint: str
    symptoms: list[str] = []
    tongue: TongueAssessment | None = None
    advice_given: str
    conversation_summary: str

    @field_validator("consultation_date")
    @classmethod
    def _assume_utc_when_naive(cls, value: datetime) -> datetime:
        return _utc_when_naive(value)


class RelevanceGateResult(BaseModel):
    """Result of summarizing a closed Consultation's working buffer.

    has_health_content=False means the Consultation is discarded with no
    Health Record entry written (memes, greetings, off-topic chat).
    """

    model_config = ConfigDict(frozen=True)

    has_health_content: bool
    entry: HealthRecordEntry | None = None
