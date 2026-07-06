"""Health Profile persistence and pure patch application (ADR 0003).

Writes happen only through apply_patch -- called by the Profile Updater
at Consultation close (gate-pass only) and by rebuild replay. Never
through an Advisor tool call. Rejected ops (unknown IDs, invalid dates)
are logged loudly and recorded in the patch log, never fuzzy-matched.
"""

import logging
from datetime import date, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.profile import (
    AppliedPatch,
    HealthProfile,
    ProfileOp,
    ProfilePatch,
)

logger = logging.getLogger(__name__)

PROFILE_COLLECTION = "health_profiles"
PATCH_COLLECTION = "profile_patches"

_ID_PREFIXES = {
    "chronic_conditions": "c",
    "allergies": "a",
    "medications": "m",
    "habits": "h",
    "ongoing_complaints": "o",
}


def empty_profile(user_id: str, now: datetime) -> HealthProfile:
    return HealthProfile(user_id=user_id, created_at=now, updated_at=now)


def apply_ops(
    profile: HealthProfile,
    ops: list[ProfileOp],
    *,
    noted_at: datetime,
    now: datetime,
) -> tuple[HealthProfile, list[ProfileOp], list[ProfileOp]]:
    """Pure: returns (new profile, applied ops, rejected ops). Never mutates."""
    data = profile.model_dump()
    applied: list[ProfileOp] = []
    rejected: list[ProfileOp] = []

    for op in ops:
        if op.op == "set_sex" and op.text:
            data["sex"] = op.text
        elif op.op == "set_notes":
            data["notes"] = op.text
        elif op.op == "set_birth_date":
            try:
                data["birth_date"] = date.fromisoformat(op.text)
            except ValueError:
                rejected.append(op)
                continue
        elif op.op == "add" and op.field in _ID_PREFIXES and op.text:
            counter = data["id_counters"].get(op.field, 0) + 1
            data["id_counters"][op.field] = counter
            data[op.field].append(
                {
                    "id": f"{_ID_PREFIXES[op.field]}{counter}",
                    "text": op.text,
                    "noted_at": noted_at,
                }
            )
        elif op.op == "update" and op.field in _ID_PREFIXES and op.text:
            match = next(
                (item for item in data[op.field] if item["id"] == op.item_id), None
            )
            if match is None:
                rejected.append(op)
                continue
            match["text"] = op.text
            match["noted_at"] = noted_at
        elif op.op == "remove" and op.field in _ID_PREFIXES:
            items = data[op.field]
            if not any(item["id"] == op.item_id for item in items):
                rejected.append(op)
                continue
            data[op.field] = [item for item in items if item["id"] != op.item_id]
        else:
            rejected.append(op)
            continue
        applied.append(op)

    data["updated_at"] = now
    return HealthProfile(**data), applied, rejected


class HealthProfileRepository:
    """One face-sheet document per user, plus an append-only patch log."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._profiles = db[PROFILE_COLLECTION]
        self._patches = db[PATCH_COLLECTION]

    async def get(self, user_id: str) -> HealthProfile | None:
        doc = await self._profiles.find_one({"user_id": user_id})
        if doc is None:
            return None
        return HealthProfile(**{k: v for k, v in doc.items() if k != "_id"})

    async def apply_patch(
        self,
        user_id: str,
        patch: ProfilePatch,
        *,
        source_consultation_date: datetime,
        now: datetime,
    ) -> HealthProfile:
        current = await self.get(user_id) or empty_profile(user_id, now)
        new_profile, applied, rejected = apply_ops(
            current, patch.ops, noted_at=source_consultation_date, now=now
        )
        if rejected:
            logger.warning(
                "Rejected %d profile op(s) for user %s: %s",
                len(rejected),
                user_id,
                [op.model_dump() for op in rejected],
            )
        await self._profiles.replace_one(
            {"user_id": user_id}, new_profile.model_dump(mode="json"), upsert=True
        )
        log_entry = AppliedPatch(
            user_id=user_id,
            source_consultation_date=source_consultation_date,
            applied_at=now,
            ops=applied,
            rejected_ops=rejected,
        )
        await self._patches.insert_one(log_entry.model_dump(mode="json"))
        return new_profile

    async def delete_for_user(self, user_id: str) -> None:
        """Rebuild support: clear the projection so replay starts clean."""
        await self._profiles.delete_one({"user_id": user_id})
        await self._patches.delete_many({"user_id": user_id})
