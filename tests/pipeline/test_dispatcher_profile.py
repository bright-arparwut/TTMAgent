from datetime import UTC, datetime

from mongomock_motor import AsyncMongoMockClient

import app.pipeline.dispatcher as dispatcher
from app.config import Settings
from app.memory.working_buffer import WorkingBufferRepository
from app.models.schemas import (
    ConsultationTurn,
    HealthRecordEntry,
    RelevanceGateResult,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

ENTRY = HealthRecordEntry(
    user_id="U1",
    consultation_date=NOW,
    chief_complaint="นอนไม่หลับ",
    symptoms=["นอนไม่หลับ"],
    advice_given="ดื่มน้ำอุ่น",
    conversation_summary="ผู้ใช้ปรึกษาเรื่องนอนไม่หลับ",
)

STALE_TURNS = [ConsultationTurn(role="user", text="นอนไม่หลับ", timestamp=NOW)]


def _settings(**overrides) -> Settings:
    return Settings(
        line_channel_secret="test", line_channel_access_token="test", **overrides
    )


class _Recorder:
    def __init__(self) -> None:
        self.updater_calls: list[str] = []
        self.profile_blocks: list[str] = []


def _patch_dispatcher(monkeypatch, recorder: _Recorder, *, stale: bool) -> None:
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(dispatcher, "get_database", lambda settings: db)

    async def fake_pop_if_stale(self, user_id, gap_hours):
        return STALE_TURNS if stale else []

    async def fake_append_turn(self, user_id, turn):
        return None

    monkeypatch.setattr(WorkingBufferRepository, "pop_if_stale", fake_pop_if_stale)
    monkeypatch.setattr(WorkingBufferRepository, "append_turn", fake_append_turn)

    async def fake_summarize(turns, *, user_id, settings):
        return RelevanceGateResult(has_health_content=True, entry=ENTRY)

    monkeypatch.setattr(dispatcher, "summarize_consultation", fake_summarize)

    async def fake_update(profile_repo, *, user_id, entry, settings, now=None):
        recorder.updater_calls.append(user_id)
        from app.memory.health_profile import empty_profile

        return empty_profile(user_id, NOW)

    monkeypatch.setattr(dispatcher, "update_profile_from_entry", fake_update)

    async def fake_retrieve(text):
        return []

    monkeypatch.setattr(dispatcher, "retrieve_passages", fake_retrieve)
    monkeypatch.setattr(dispatcher, "build_advisor_agent", lambda settings, tools: None)

    async def fake_run_advisor(agent, *, user_message, retrieved_passages,
                               recent_records_summary, health_profile_block="",
                               history=()):
        recorder.profile_blocks.append(health_profile_block)
        return "คำตอบ"

    monkeypatch.setattr(dispatcher, "run_advisor", fake_run_advisor)


async def test_gate_pass_triggers_updater_and_injects_profile(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, stale=True)

    reply = await dispatcher._run_consultation_turn("U1", "สวัสดี", _settings())

    assert reply.visible_text == "คำตอบ"
    assert recorder.updater_calls == ["U1"]
    assert recorder.profile_blocks[0] != ""  # rendered profile injected


async def test_flag_off_skips_updater_and_injection(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, stale=True)

    await dispatcher._run_consultation_turn(
        "U1", "สวัสดี", _settings(health_profile_enabled=False)
    )

    assert recorder.updater_calls == []
    assert recorder.profile_blocks == [""]


async def test_no_stale_buffer_means_no_update_but_still_injects(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, stale=False)

    await dispatcher._run_consultation_turn("U1", "สวัสดี", _settings())

    assert recorder.updater_calls == []
    assert recorder.profile_blocks[0] != ""
