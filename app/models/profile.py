"""Health Profile domain models (see docs/adr/0003-health-profile-projection.md).

The profile is a per-user face sheet maintained as a deterministic
projection of Health Record entries. It is patched -- never rewritten --
by the Profile Updater at Consultation close, and injected whole into
every Advisor turn. The Advisor has no profile tools.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

LIST_FIELDS = (
    "chronic_conditions",
    "allergies",
    "medications",
    "habits",
    "ongoing_complaints",
)

ListField = Literal[
    "chronic_conditions", "allergies", "medications", "habits", "ongoing_complaints"
]


class ProfileItem(BaseModel):
    """One fact on the face sheet. noted_at is the consultation_date of the
    Health Record entry that added or last updated it (provenance)."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    noted_at: datetime


class HealthProfile(BaseModel):
    """The face sheet: current state only. Resolved items are removed (their
    history survives in the patch log and the Health Record). id_counters
    are monotonic per list field so removed item IDs are never reused."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    sex: str | None = None
    birth_date: date | None = None
    chronic_conditions: list[ProfileItem] = []
    allergies: list[ProfileItem] = []
    medications: list[ProfileItem] = []
    habits: list[ProfileItem] = []
    ongoing_complaints: list[ProfileItem] = []
    notes: str = ""
    id_counters: dict[str, int] = {}
    created_at: datetime
    updated_at: datetime


class ProfileOp(BaseModel):
    """One patch operation. Flat (no discriminated union) so weaker Advisor
    slots can emit it reliably as structured output. set_birth_date carries
    an ISO date in text; add/update/remove target a list field, with
    update/remove referencing an existing item_id."""

    model_config = ConfigDict(frozen=True)

    op: Literal["set_sex", "set_birth_date", "set_notes", "add", "update", "remove"]
    field: ListField | None = None
    item_id: str = ""
    text: str = ""


class ProfilePatch(BaseModel):
    """The Profile Updater's structured output: zero or more ops."""

    model_config = ConfigDict(frozen=True)

    ops: list[ProfileOp] = []


class AppliedPatch(BaseModel):
    """Audit-log document: what was applied (and rejected) at one close."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    source_consultation_date: datetime
    applied_at: datetime
    ops: list[ProfileOp] = []
    rejected_ops: list[ProfileOp] = []
