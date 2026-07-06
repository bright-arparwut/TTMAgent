"""Profile Updater: fold one Health Record entry into the Health Profile.

The projection invariant (ADR 0003): input is always (current profile +
one entry) -- never the raw transcript -- so close-time updates and
rebuild-by-replay are the same code path, and the profile is rebuildable
from the record at any time. LLM-scored but code-triggered, like the
Relevance Gate. The Advisor cannot invoke this.
"""

from datetime import UTC, datetime

from app.advisor.llm import build_chat_model
from app.config import Settings
from app.memory.health_profile import HealthProfileRepository, empty_profile
from app.memory.health_record import HealthRecordRepository
from app.memory.profile_render import render_profile
from app.models.profile import HealthProfile, ProfilePatch
from app.models.schemas import HealthRecordEntry

UPDATE_PROMPT = """\
You maintain the Health Profile of a user of a Thai Traditional Medicine \
self-care advisor. The profile is a face sheet of their CURRENT state \
(sex, birth date, chronic conditions, allergies, regular medicines/herbs, \
habits, ongoing complaints).

Current profile — list items are labeled with stable IDs in brackets:
{profile}

A consultation just closed. Its Health Record entry:
{entry}

Emit patch operations that bring the profile up to date. Rules:
- Only state facts explicitly present in the entry. Never invent.
- To change or resolve an existing fact, use update/remove with the exact \
ID shown in brackets. Never invent IDs.
- Use add only for facts not already on the profile.
- set_birth_date only if the entry states a birth date; text must be an \
ISO date (YYYY-MM-DD).
- An ongoing complaint the user reports as resolved should be removed.
- If the entry adds nothing profile-worthy, return an empty ops list.
"""


def _render_entry(entry: HealthRecordEntry) -> str:
    lines = [
        f"Consultation date: {entry.consultation_date.date().isoformat()}",
        f"Chief complaint: {entry.chief_complaint}",
    ]
    if entry.symptoms:
        lines.append("Symptoms: " + ", ".join(entry.symptoms))
    lines.append(f"Advice given: {entry.advice_given}")
    lines.append(f"Summary: {entry.conversation_summary}")
    return "\n".join(lines)


async def update_profile_from_entry(
    profile_repo: HealthProfileRepository,
    *,
    user_id: str,
    entry: HealthRecordEntry,
    settings: Settings,
    now: datetime | None = None,
) -> HealthProfile:
    now = now or datetime.now(UTC)
    current = await profile_repo.get(user_id) or empty_profile(user_id, now)

    prompt = UPDATE_PROMPT.format(
        profile=render_profile(current, today=now.date()),
        entry=_render_entry(entry),
    )
    model = build_chat_model(settings.advisor_slot())
    patch: ProfilePatch = await model.with_structured_output(ProfilePatch).ainvoke(prompt)

    return await profile_repo.apply_patch(
        user_id, patch, source_consultation_date=entry.consultation_date, now=now
    )


async def rebuild_profile(
    profile_repo: HealthProfileRepository,
    record_repo: HealthRecordRepository,
    *,
    user_id: str,
    settings: Settings,
) -> HealthProfile | None:
    """Rebuild the projection by replaying all entries chronologically.

    Note: rebuilding discards the original patch log, so `applied_at`
    history on the rebuilt profile's items resets to rebuild time rather
    than reflecting the original close-time updates.
    """
    entries = await record_repo.all_for_user(user_id)
    if not entries:
        return None
    await profile_repo.delete_for_user(user_id)
    profile: HealthProfile | None = None
    for entry in entries:
        profile = await update_profile_from_entry(
            profile_repo, user_id=user_id, entry=entry, settings=settings
        )
    return profile
