"""ADR 0006 wiring: the Working Buffer stores the RAW Advisor reply
(delimiter block included) while LINE receives the visible text with the
topics as Quick Reply buttons."""

from types import SimpleNamespace

from mongomock_motor import AsyncMongoMockClient

import app.pipeline.dispatcher as dispatcher
from app.advisor.topic_menu import TOPIC_MENU_MARKER
from app.config import Settings
from app.memory.working_buffer import WorkingBufferRepository

VISIBLE = "ธาตุเจ้าเรือนของคุณน่าจะเป็นธาตุไฟค่ะ"
RAW_WITH_MENU = f"{VISIBLE}\n\n{TOPIC_MENU_MARKER}\n- อาหารบำรุงธาตุไฟ\n- ท่าบริหารตอนเช้า"


def _settings() -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test")


def _event() -> SimpleNamespace:
    return SimpleNamespace(
        source=SimpleNamespace(user_id="U1"),
        message=SimpleNamespace(text="ขอคำแนะนำค่ะ"),
        reply_token="R1",
    )


class _FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[str, ...]]] = []

    async def reply_or_push(self, *, reply_token, user_id, text, topics=()) -> None:
        self.sent.append((text, tuple(topics)))


def _patch_spine(monkeypatch, advisor_reply: str) -> tuple[_FakeMessenger, list]:
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(dispatcher, "get_database", lambda settings: db)

    messenger = _FakeMessenger()
    monkeypatch.setattr(dispatcher, "LineMessenger", lambda settings: messenger)

    appended = []

    async def fake_pop_if_stale(self, user_id, gap_hours):
        return None

    async def fake_current_turns(self, user_id):
        return []

    async def fake_append_turn(self, user_id, turn):
        appended.append(turn)

    monkeypatch.setattr(WorkingBufferRepository, "pop_if_stale", fake_pop_if_stale)
    monkeypatch.setattr(WorkingBufferRepository, "current_turns", fake_current_turns)
    monkeypatch.setattr(WorkingBufferRepository, "append_turn", fake_append_turn)

    async def fake_retrieve(text):
        return []

    monkeypatch.setattr(dispatcher, "retrieve_passages", fake_retrieve)
    monkeypatch.setattr(dispatcher, "build_advisor_agent", lambda settings, tools: None)

    async def fake_run_advisor(agent, **kwargs):
        return advisor_reply

    monkeypatch.setattr(dispatcher, "run_advisor", fake_run_advisor)
    return messenger, appended


async def test_menu_reply_stores_raw_and_sends_visible_with_topics(monkeypatch):
    messenger, appended = _patch_spine(monkeypatch, RAW_WITH_MENU)

    await dispatcher.handle_text_message(_event(), _settings())

    advisor_turns = [turn for turn in appended if turn.role == "advisor"]
    assert advisor_turns[0].text == RAW_WITH_MENU  # block survives in the buffer
    assert messenger.sent == [(VISIBLE, ("อาหารบำรุงธาตุไฟ", "ท่าบริหารตอนเช้า"))]


async def test_plain_reply_sends_full_text_with_no_topics(monkeypatch):
    messenger, appended = _patch_spine(monkeypatch, VISIBLE)

    await dispatcher.handle_text_message(_event(), _settings())

    advisor_turns = [turn for turn in appended if turn.role == "advisor"]
    assert advisor_turns[0].text == VISIBLE
    assert messenger.sent == [(VISIBLE, ())]
