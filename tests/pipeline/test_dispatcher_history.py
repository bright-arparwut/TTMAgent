"""Working Buffer replay wiring in the consultation spine (ADR 0005):
history is loaded before the incoming turn is appended, capped by config,
and handed to the Advisor.
"""

from datetime import UTC, datetime
from typing import Literal

from mongomock_motor import AsyncMongoMockClient

import app.pipeline.dispatcher as dispatcher
from app.config import Settings
from app.memory.working_buffer import WorkingBufferRepository
from app.models.schemas import ConsultationTurn

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _settings(**overrides) -> Settings:
    return Settings(
        line_channel_secret="test", line_channel_access_token="test", **overrides
    )


def _turn(role: Literal["user", "advisor"], text: str) -> ConsultationTurn:
    return ConsultationTurn(role=role, text=text, timestamp=NOW)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.advisor_history: list[ConsultationTurn] | None = None


def _patch_dispatcher(
    monkeypatch, recorder: _Recorder, *, buffer_turns: list[ConsultationTurn]
) -> None:
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(dispatcher, "get_database", lambda settings: db)

    async def fake_pop_if_stale(self, user_id, gap_hours):
        return None

    async def fake_current_turns(self, user_id):
        recorder.events.append("load_history")
        return list(buffer_turns)

    async def fake_append_turn(self, user_id, turn):
        recorder.events.append(f"append:{turn.role}")

    monkeypatch.setattr(WorkingBufferRepository, "pop_if_stale", fake_pop_if_stale)
    monkeypatch.setattr(WorkingBufferRepository, "current_turns", fake_current_turns)
    monkeypatch.setattr(WorkingBufferRepository, "append_turn", fake_append_turn)

    async def fake_retrieve(text):
        return []

    monkeypatch.setattr(dispatcher, "retrieve_passages", fake_retrieve)
    monkeypatch.setattr(dispatcher, "build_advisor_agent", lambda settings, tools: None)

    async def fake_run_advisor(
        agent,
        *,
        user_message,
        retrieved_passages,
        recent_records_summary,
        health_profile_block="",
        history=(),
    ):
        recorder.events.append("run_advisor")
        recorder.advisor_history = list(history)
        return "คำตอบ"

    monkeypatch.setattr(dispatcher, "run_advisor", fake_run_advisor)


async def test_history_is_loaded_before_incoming_turn_is_appended(monkeypatch):
    recorder = _Recorder()
    prior = [_turn("user", "ปวดหัว"), _turn("advisor", "นานแค่ไหนคะ")]
    _patch_dispatcher(monkeypatch, recorder, buffer_turns=prior)

    await dispatcher._run_consultation_turn("U1", "สามวันค่ะ", _settings())

    assert recorder.events.index("load_history") < recorder.events.index("append:user")
    assert recorder.advisor_history == prior


async def test_history_is_capped_to_last_n_turns_from_config(monkeypatch):
    recorder = _Recorder()
    prior = [_turn("user", f"ข้อความ {i}") for i in range(5)]
    _patch_dispatcher(monkeypatch, recorder, buffer_turns=prior)

    await dispatcher._run_consultation_turn(
        "U1", "ล่าสุด", _settings(advisor_history_max_turns=2)
    )

    assert recorder.advisor_history == prior[-2:]


async def test_history_cap_of_zero_sends_no_history(monkeypatch):
    """cap=0 must disable replay entirely (the memory-ablation arm), not
    fall into Python's -0 == 0 slice trap that returns the whole buffer."""
    recorder = _Recorder()
    prior = [_turn("user", f"ข้อความ {i}") for i in range(3)]
    _patch_dispatcher(monkeypatch, recorder, buffer_turns=prior)

    await dispatcher._run_consultation_turn(
        "U1", "ล่าสุด", _settings(advisor_history_max_turns=0)
    )

    assert recorder.advisor_history == []


async def test_empty_buffer_passes_empty_history(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, buffer_turns=[])

    await dispatcher._run_consultation_turn("U1", "สวัสดี", _settings())

    assert recorder.advisor_history == []


def test_advisor_history_max_turns_defaults_to_30():
    assert _settings().advisor_history_max_turns == 30
