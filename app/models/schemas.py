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

    Five of the six inspection axes named by '100 ลักษณะวินิจฉัยลิ้น' ch. 12
    (see CONTEXT.md -> Tongue Description): color/สี, coating/ฝ้า, size/ขนาด,
    shape/รูปร่าง, spots/จุดบนลิ้น. Free Thai text, not enums -- issue #36's
    landing-rate check (docs/adr/0010) found steered free text lands on the
    graph's node names well enough (~96%) that Literal-hardening buys
    nothing and would force compound observations into a single term.
    `shape` also covers cracks/teeth marks (ch. 12 notes 207 + 210); the
    sixth axis, การเคลื่อนไหว, and sublingual veins are deliberately absent --
    a still top-side crop cannot witness either, and `notes` is the escape
    hatch for the rare visible case. `moisture` is not a separate field:
    its content folds into `color`/`coating` via the describer prompt (e.g.
    ชื้น/แห้ง as part of a color or coating observation).
    """

    model_config = ConfigDict(frozen=True)

    color: str
    coating: str
    size: str
    shape: str
    spots: str
    notes: str = ""
    quality: Literal["clear", "blurry", "partial", "poor_lighting"]


class TonguePhoto(BaseModel):
    """One Roboflow crop persisted for the thesis dataset (ADR 0007).

    Deliberately outside the memory architecture: survives Consultation
    close and gate-failed discards. `image` is raw JPEG bytes (stored as
    BSON Binary, never base64). `description` stays None until the Vision
    Describer returns -- a null description marks a describer-stage failure.
    """

    model_config = ConfigDict(frozen=True)

    photo_id: str
    user_id: str
    image: bytes
    captured_at: datetime
    confidence: float
    passed_gate: bool
    line_message_id: str
    description: TongueDescription | None = None

    @field_validator("captured_at")
    @classmethod
    def _assume_utc_when_naive(cls, value: datetime) -> datetime:
        return _utc_when_naive(value)


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
