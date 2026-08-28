"""ADR 0010's citation contract wired into the dispatcher spine:

- The retrieval query concatenates the last 2-3 user turns from the
  Working Buffer with the incoming text ("The retrieval seam").
- render_references resolves the Advisor's bare-id citation before the
  Working Buffer write, so the buffer (and the Advisor's own turn
  history) holds the resolved citation, never the bare ids ("The
  citation contract").
"""

from datetime import UTC, datetime
from pathlib import Path

from mongomock_motor import AsyncMongoMockClient

import app.advisor.citation as citation_module
import app.pipeline.dispatcher as dispatcher
from app.config import Settings
from app.memory.working_buffer import WorkingBufferRepository
from app.models.schemas import ConsultationTurn

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _settings(**overrides) -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test", **overrides)


def _turn(role: str, text: str) -> ConsultationTurn:
    return ConsultationTurn(role=role, text=text, timestamp=NOW)


def _write_note(corpus_dir: Path, book_id: str, filename: str) -> None:
    book_dir = corpus_dir / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / f"{filename}.md").write_text("---\nuid: x\n---\nbody\n", encoding="utf-8")


def _write_books_yaml(corpus_dir: Path, books: dict[str, str]) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{book_id}: {title}" for book_id, title in books.items()]
    (corpus_dir / "books.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Recorder:
    def __init__(self) -> None:
        self.retrieval_queries: list[str] = []
        self.appended: list[ConsultationTurn] = []


def _patch_dispatcher(
    monkeypatch, recorder: _Recorder, *, buffer_turns, advisor_reply: str, passages: list[str]
) -> None:
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(dispatcher, "get_database", lambda settings: db)

    async def fake_pop_if_stale(self, user_id, gap_hours):
        return None

    async def fake_current_turns(self, user_id):
        return list(buffer_turns)

    async def fake_append_turn(self, user_id, turn):
        recorder.appended.append(turn)

    monkeypatch.setattr(WorkingBufferRepository, "pop_if_stale", fake_pop_if_stale)
    monkeypatch.setattr(WorkingBufferRepository, "current_turns", fake_current_turns)
    monkeypatch.setattr(WorkingBufferRepository, "append_turn", fake_append_turn)

    async def fake_retrieve(query):
        recorder.retrieval_queries.append(query)
        return passages

    monkeypatch.setattr(dispatcher, "retrieve_passages", fake_retrieve)
    monkeypatch.setattr(dispatcher, "build_advisor_agent", lambda settings, tools: None)

    async def fake_run_advisor(agent, **kwargs):
        return advisor_reply

    monkeypatch.setattr(dispatcher, "run_advisor", fake_run_advisor)


async def test_retrieval_query_includes_incoming_text_and_recent_user_turns(monkeypatch):
    recorder = _Recorder()
    prior = [
        _turn("user", "ปวดหัว"),
        _turn("advisor", "นานแค่ไหนคะ"),
        _turn("user", "สามวันแล้ว"),
        _turn("advisor", "มีไข้ไหมคะ"),
        _turn("user", "ไม่มีไข้"),
    ]
    _patch_dispatcher(monkeypatch, recorder, buffer_turns=prior, advisor_reply="คำตอบ", passages=[])

    await dispatcher._run_consultation_turn("U1", "ล่าสุดค่ะ", _settings())

    assert len(recorder.retrieval_queries) == 1
    query = recorder.retrieval_queries[0]
    assert "ล่าสุดค่ะ" in query
    # Oldest-first ordering, incoming text last.
    assert query.index("สามวันแล้ว") < query.index("ไม่มีไข้") < query.index("ล่าสุดค่ะ")
    # Advisor-role turns are not user turns -- must not leak into the query.
    assert "นานแค่ไหนคะ" not in query
    assert "มีไข้ไหมคะ" not in query


async def test_retrieval_query_caps_to_last_few_user_turns(monkeypatch):
    recorder = _Recorder()
    prior = [_turn("user", f"ข้อความ {i}") for i in range(6)]
    _patch_dispatcher(monkeypatch, recorder, buffer_turns=prior, advisor_reply="คำตอบ", passages=[])

    await dispatcher._run_consultation_turn("U1", "ล่าสุด", _settings())

    query = recorder.retrieval_queries[0]
    assert "ข้อความ 0" not in query
    assert "ข้อความ 1" not in query
    assert "ข้อความ 5" in query


async def test_empty_buffer_retrieval_query_is_just_the_incoming_text(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, buffer_turns=[], advisor_reply="คำตอบ", passages=[])

    await dispatcher._run_consultation_turn("U1", "สวัสดี", _settings())

    assert recorder.retrieval_queries == ["สวัสดี"]


async def test_render_references_runs_before_the_working_buffer_write(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    monkeypatch.setattr(
        citation_module, "get_settings", lambda: _settings(corpus_dir=str(corpus_dir))
    )

    recorder = _Recorder()
    passages = ["[1] 001-a-น.1-4\nเนื้อหา"]
    advisor_reply = "คำแนะนำของฉัน\n(อ้างอิง: [1])"
    _patch_dispatcher(
        monkeypatch, recorder, buffer_turns=[], advisor_reply=advisor_reply, passages=passages
    )

    parsed = await dispatcher._run_consultation_turn("U1", "ปวดหัว", _settings())

    rendered = "คำแนะนำของฉัน\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4)"
    advisor_turns = [turn for turn in recorder.appended if turn.role == "advisor"]
    assert advisor_turns[0].text == rendered  # Working Buffer holds the resolved citation.
    assert parsed.visible_text == rendered  # ...and so does the reply sent to the caller.


async def test_an_invented_id_disappears_before_the_working_buffer_write(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    monkeypatch.setattr(
        citation_module, "get_settings", lambda: _settings(corpus_dir=str(corpus_dir))
    )

    recorder = _Recorder()
    # Only [1] was ever handed to the Advisor -- [9] is invented.
    passages = ["[1] 001-a-น.1-4\nเนื้อหา"]
    advisor_reply = "คำแนะนำของฉัน\n(อ้างอิง: [1] [9])"
    _patch_dispatcher(
        monkeypatch, recorder, buffer_turns=[], advisor_reply=advisor_reply, passages=passages
    )

    parsed = await dispatcher._run_consultation_turn("U1", "ปวดหัว", _settings())

    assert "9" not in parsed.visible_text.split("(อ้างอิง:")[1]
    assert "100 ลักษณะวินิจฉัยลิ้น หน้า 1-4" in parsed.visible_text
