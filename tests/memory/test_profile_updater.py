from datetime import UTC, datetime

from mongomock_motor import AsyncMongoMockClient

import app.memory.profile_updater as updater_module
from app.memory.health_profile import HealthProfileRepository
from app.memory.health_record import HealthRecordRepository
from app.memory.profile_updater import rebuild_profile, update_profile_from_entry
from app.models.profile import ProfileOp, ProfilePatch
from app.models.schemas import HealthRecordEntry

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _entry(day: int, complaint: str) -> HealthRecordEntry:
    return HealthRecordEntry(
        user_id="U1",
        consultation_date=datetime(2026, 7, day, 9, 0, tzinfo=UTC),
        chief_complaint=complaint,
        symptoms=[complaint],
        advice_given="ดื่มน้ำอุ่น พักผ่อน",
        conversation_summary=f"ผู้ใช้ปรึกษาเรื่อง{complaint}",
    )


PATCHES_BY_COMPLAINT = {
    "นอนไม่หลับ": ProfilePatch(
        ops=[ProfileOp(op="add", field="ongoing_complaints", text="นอนไม่หลับ ~2 สัปดาห์")]
    ),
    "ปวดหัว": ProfilePatch(
        ops=[
            ProfileOp(op="add", field="habits", text="นอนดึกตี 1-2"),
            ProfileOp(op="set_sex", text="ชาย"),
        ]
    ),
}


class _FakeStructuredModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        assert schema is ProfilePatch
        return self

    async def ainvoke(self, prompt: str) -> ProfilePatch:
        self.prompts.append(prompt)
        # Match on the entry-section marker only: the rendered profile
        # legitimately echoes prior complaint text (the projection carries
        # it forward), so a bare-substring match would re-match old entries.
        for complaint, patch in PATCHES_BY_COMPLAINT.items():
            if f"Chief complaint: {complaint}" in prompt:
                return patch
        return ProfilePatch()


def _settings():
    from app.config import Settings

    return Settings(line_channel_secret="test", line_channel_access_token="test")


async def test_update_builds_prompt_from_profile_and_entry_only(monkeypatch):
    fake = _FakeStructuredModel()
    monkeypatch.setattr(updater_module, "build_chat_model", lambda slot: fake)
    repo = HealthProfileRepository(AsyncMongoMockClient()["test_db"])

    entry = _entry(1, "นอนไม่หลับ")
    profile = await update_profile_from_entry(
        repo, user_id="U1", entry=entry, settings=_settings(), now=NOW
    )

    assert [i.text for i in profile.ongoing_complaints] == ["นอนไม่หลับ ~2 สัปดาห์"]
    assert profile.ongoing_complaints[0].noted_at == entry.consultation_date
    prompt = fake.prompts[0]
    assert "ยังไม่มีข้อมูล" in prompt  # rendered (empty) profile is in the prompt
    assert "นอนไม่หลับ" in prompt  # the entry is in the prompt
    assert "user:" not in prompt and "advisor:" not in prompt  # never a transcript


async def test_rebuild_replays_entries_and_matches_incremental(monkeypatch):
    fake = _FakeStructuredModel()
    monkeypatch.setattr(updater_module, "build_chat_model", lambda slot: fake)
    db = AsyncMongoMockClient()["test_db"]
    profile_repo = HealthProfileRepository(db)
    record_repo = HealthRecordRepository(db)

    entries = [_entry(1, "นอนไม่หลับ"), _entry(3, "ปวดหัว")]
    for entry in entries:
        await record_repo.insert(entry)

    incremental = None
    for entry in entries:
        incremental = await update_profile_from_entry(
            profile_repo, user_id="U1", entry=entry, settings=_settings(), now=NOW
        )

    rebuilt = await rebuild_profile(
        profile_repo, record_repo, user_id="U1", settings=_settings()
    )

    assert rebuilt is not None and incremental is not None
    exclude = {"created_at", "updated_at"}
    assert rebuilt.model_dump(exclude=exclude) == incremental.model_dump(exclude=exclude)
    assert rebuilt.sex == "ชาย"
    assert [i.id for i in rebuilt.ongoing_complaints] == ["o1"]
    assert [i.id for i in rebuilt.habits] == ["h1"]


async def test_rebuild_with_no_entries_returns_none(monkeypatch):
    fake = _FakeStructuredModel()
    monkeypatch.setattr(updater_module, "build_chat_model", lambda slot: fake)
    db = AsyncMongoMockClient()["test_db"]
    result = await rebuild_profile(
        HealthProfileRepository(db),
        HealthRecordRepository(db),
        user_id="U-nobody",
        settings=_settings(),
    )
    assert result is None
