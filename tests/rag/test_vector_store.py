import logging

import pytest

import app.rag.vector_store as vector_store_module
from app.config import Settings
from app.rag.vector_store import retrieve_passages


def _settings(**overrides) -> Settings:
    return Settings(
        line_channel_secret="test",
        line_channel_access_token="test",
        **overrides,
    )


def _async_return(value):
    """A zero-arg async callable returning `value` -- for monkeypatching
    `get_rag`, which callers `await`."""

    async def _inner():
        return value

    return _inner


class _FakeTokenizer:
    """One "token" per character: deterministic and language-agnostic, so
    budget tests can size Thai fixture text by plain `len()`."""

    def encode(self, text: str) -> list[str]:
        return list(text)


class _FakeRAG:
    def __init__(self, responses: dict[str, dict | BaseException]) -> None:
        self.tokenizer = _FakeTokenizer()
        self._responses = responses
        self.calls: list[str] = []

    async def aquery_data(self, query: str, param) -> dict:
        self.calls.append(param.mode)
        response = self._responses[param.mode]
        if isinstance(response, BaseException):
            raise response
        return response


def _write_note(corpus_dir, book_id: str, filename: str, body: str) -> None:
    book_dir = corpus_dir / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / filename).write_text(
        "---\n"
        f"uid: {book_id}-{filename}\n"
        "type: source-note\n"
        f"book_id: {book_id}\n"
        "chapter: บทที่ 1\n"
        "section: ทดสอบ\n"
        "pages: [1, 2]\n"
        "pdf_pages: [1, 2]\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


async def test_relations_in_entities_out(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "corpus"
    _write_note(corpus_dir, "four-elements", "01-บทนำ-น.13-16.md", "เนื้อหาบทนำ")
    settings = _settings(corpus_dir=str(corpus_dir))
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)

    raw = {
        "status": "success",
        "data": {
            "entities": [
                {
                    "entity_name": "ธาตุไฟ",
                    "entity_type": "concept",
                    "description": "คำอธิบายธาตุไฟ",
                }
            ],
            "relationships": [
                {
                    "src_id": "ธาตุไฟ",
                    "tgt_id": "ธาตุดิน",
                    "description": "สัมพันธ์กัน",
                    "file_path": "01-บทนำ-น.13-16.md",
                }
            ],
            "chunks": [],
            "references": [{"reference_id": "1", "file_path": "01-บทนำ-น.13-16.md"}],
        },
        "metadata": {"query_mode": "mix"},
    }
    monkeypatch.setattr(vector_store_module, "get_rag", _async_return(_FakeRAG({"mix": raw})))

    passages = await retrieve_passages("ธาตุไฟกำเริบ ควรดูแลตัวเองอย่างไร")

    # The relation's own note is the one numbered passage.
    assert passages[0] == "[1] 01-บทนำ-น.13-16\nเนื้อหาบทนำ"
    numbered = [p for p in passages if not p.startswith(vector_store_module.GRAPH_CONTEXT_LABEL)]
    assert len(numbered) == 1

    # The entity contributes no numbered note of its own -- it only shows up
    # (unnumbered) in the trailing graph-context passage.
    assert passages[-1].startswith(vector_store_module.GRAPH_CONTEXT_LABEL)
    assert "ธาตุไฟ" in passages[-1]
    assert "คำอธิบายธาตุไฟ" in passages[-1]


async def test_whole_note_expansion_from_temp_corpus_tree(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "corpus"
    _write_note(
        corpus_dir,
        "tongue-100",
        "006-การตรวจลิ้น-น.9-9.md",
        "ลิ้นเป็นแผลเล็ก ๆ เรื้อรังในโรคไฟธาตุหย่อน",
    )
    settings = _settings(corpus_dir=str(corpus_dir))
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)

    raw = {
        "status": "success",
        "data": {
            "entities": [],
            "relationships": [
                {
                    "src_id": "ลิ้น",
                    "tgt_id": "โรคไฟธาตุหย่อน",
                    # Empty description: this test is about whole-note expansion, not
                    # the graph-context block (covered by test_relations_in_entities_out).
                    "description": "",
                    "file_path": "006-การตรวจลิ้น-น.9-9.md",
                }
            ],
            "chunks": [],
            "references": [{"reference_id": "1", "file_path": "006-การตรวจลิ้น-น.9-9.md"}],
        },
        "metadata": {"query_mode": "mix"},
    }
    monkeypatch.setattr(vector_store_module, "get_rag", _async_return(_FakeRAG({"mix": raw})))

    passages = await retrieve_passages("ลิ้นเป็นแผล")

    assert passages == ["[1] 006-การตรวจลิ้น-น.9-9\nลิ้นเป็นแผลเล็ก ๆ เรื้อรังในโรคไฟธาตุหย่อน"]


async def test_oversized_note_falls_back_to_chunk_text_within_budget(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "corpus"
    oversized_body = "เนื้อหายาวมาก " * 200  # far larger than the token budget below
    _write_note(corpus_dir, "four-elements", "01-บทนำ-น.13-16.md", oversized_body)
    settings = _settings(corpus_dir=str(corpus_dir), rag_section_token_budget=100)
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)

    raw = {
        "status": "success",
        "data": {
            "entities": [],
            "relationships": [
                {
                    "src_id": "a",
                    "tgt_id": "b",
                    "description": "",
                    "file_path": "01-บทนำ-น.13-16.md",
                }
            ],
            "chunks": [
                {
                    "reference_id": "1",
                    "content": "สรุปสั้น",
                    "file_path": "01-บทนำ-น.13-16.md",
                    "chunk_id": "c1",
                }
            ],
            "references": [{"reference_id": "1", "file_path": "01-บทนำ-น.13-16.md"}],
        },
        "metadata": {"query_mode": "mix"},
    }
    monkeypatch.setattr(vector_store_module, "get_rag", _async_return(_FakeRAG({"mix": raw})))

    passages = await retrieve_passages("q")

    assert passages == ["[1] 01-บทนำ-น.13-16\nสรุปสั้น"]


async def test_numbering_is_sequential_and_dedupes_by_file_path(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "corpus"  # deliberately empty -- forces chunk fallback
    corpus_dir.mkdir()
    settings = _settings(corpus_dir=str(corpus_dir))
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)

    chunks = [
        {"reference_id": "1", "content": "เนื้อหา A", "file_path": "01-a-น.1-1.md", "chunk_id": "c1"},
        {"reference_id": "2", "content": "เนื้อหา B", "file_path": "02-b-น.2-2.md", "chunk_id": "c2"},
    ]
    raw = {
        "status": "success",
        "data": {
            "entities": [],
            "relationships": [
                {"src_id": "x", "tgt_id": "y", "description": "", "file_path": "01-a-น.1-1.md"},
                {"src_id": "y", "tgt_id": "z", "description": "", "file_path": "02-b-น.2-2.md"},
                # Same file_path as the first relation -- must collapse to [1],
                # not get its own number.
                {"src_id": "x", "tgt_id": "z", "description": "", "file_path": "01-a-น.1-1.md"},
            ],
            "chunks": chunks,
            "references": [
                {"reference_id": "1", "file_path": "01-a-น.1-1.md"},
                {"reference_id": "2", "file_path": "02-b-น.2-2.md"},
            ],
        },
        "metadata": {"query_mode": "mix"},
    }
    monkeypatch.setattr(vector_store_module, "get_rag", _async_return(_FakeRAG({"mix": raw})))

    passages = await retrieve_passages("q")

    assert passages == ["[1] 01-a-น.1-1\nเนื้อหา A", "[2] 02-b-น.2-2\nเนื้อหา B"]


async def test_naive_mode_uses_chunks_as_references_when_no_relations_exist(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    settings = _settings(corpus_dir=str(corpus_dir), rag_query_mode="naive")
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)

    raw = {
        "status": "success",
        "data": {
            "entities": [],
            "relationships": [],
            "chunks": [
                {
                    "reference_id": "1",
                    "content": "เนื้อหาจากการค้นแบบ naive",
                    "file_path": "01-บทนำ-น.13-16.md",
                    "chunk_id": "c1",
                }
            ],
            "references": [{"reference_id": "1", "file_path": "01-บทนำ-น.13-16.md"}],
        },
        "metadata": {"query_mode": "naive"},
    }
    monkeypatch.setattr(vector_store_module, "get_rag", _async_return(_FakeRAG({"naive": raw})))

    passages = await retrieve_passages("q")

    assert passages == ["[1] 01-บทนำ-น.13-16\nเนื้อหาจากการค้นแบบ naive"]


async def test_keyword_failure_degrades_to_naive_logged_at_error(tmp_path, caplog, monkeypatch):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    settings = _settings(corpus_dir=str(corpus_dir))
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)

    naive_raw = {
        "status": "success",
        "data": {
            "entities": [],
            "relationships": [],
            "chunks": [
                {
                    "reference_id": "1",
                    "content": "เนื้อหาสำรอง",
                    "file_path": "01-บทนำ-น.13-16.md",
                    "chunk_id": "c1",
                }
            ],
            "references": [{"reference_id": "1", "file_path": "01-บทนำ-น.13-16.md"}],
        },
        "metadata": {"query_mode": "naive"},
    }
    fake_rag = _FakeRAG({"mix": RuntimeError("keyword LLM unavailable"), "naive": naive_raw})
    monkeypatch.setattr(vector_store_module, "get_rag", _async_return(fake_rag))

    with caplog.at_level(logging.ERROR, logger="app.rag.vector_store"):
        passages = await retrieve_passages("ธาตุไฟกำเริบ ควรดูแลตัวเองอย่างไร")

    assert fake_rag.calls == ["mix", "naive"]
    assert passages == ["[1] 01-บทนำ-น.13-16\nเนื้อหาสำรอง"]
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert "naive" in caplog.records[0].message


async def test_both_modes_failing_returns_empty_list_logged_at_error(tmp_path, caplog, monkeypatch):
    settings = _settings(corpus_dir=str(tmp_path / "corpus"))
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)
    fake_rag = _FakeRAG({"mix": RuntimeError("boom"), "naive": RuntimeError("boom again")})
    monkeypatch.setattr(vector_store_module, "get_rag", _async_return(fake_rag))

    with caplog.at_level(logging.ERROR, logger="app.rag.vector_store"):
        passages = await retrieve_passages("q")

    assert passages == []
    assert fake_rag.calls == ["mix", "naive"]
    assert len(caplog.records) == 2
    assert all(record.levelno == logging.ERROR for record in caplog.records)


async def test_missing_store_files_raise_at_boot_naming_rebuild_command(tmp_path, monkeypatch):
    settings = _settings(rag_storage_dir=str(tmp_path / "rag_storage"))
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)
    monkeypatch.setattr(vector_store_module, "_rag", None)

    with pytest.raises(RuntimeError, match="lightrag-rebuild-vdb"):
        await vector_store_module.get_rag()


async def test_concepts_directory_is_never_mistaken_for_a_book_in_note_body_lookup(
    tmp_path, monkeypatch
):
    """corpus/concepts/ (Phase 6, #17) is the generated vault, not a book --
    even a same-named file living there must not be returned by _find_note_body,
    which would otherwise confuse a concepts note with a real source note."""
    corpus_dir = tmp_path / "corpus"
    # Write the same filename to both concepts/ and a real book dir
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4.md", "book note body")
    concepts_dir = corpus_dir / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    (concepts_dir / "001-a-น.1-4.md").write_text(
        "---\nuid: concept-uid\n---\nconcept note body\n",
        encoding="utf-8",
    )
    settings = _settings(corpus_dir=str(corpus_dir))
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)

    # _find_note_body should find the book version, not the concepts version
    result = vector_store_module._find_note_body(corpus_dir, "001-a-น.1-4.md")
    assert result == "book note body"
