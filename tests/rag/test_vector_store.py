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


class _FakeDocument:
    def __init__(self, page_content: str, metadata: dict | None = None) -> None:
        self.page_content = page_content
        self.metadata = metadata or {}


class _FakeStore:
    def __init__(self, documents: list[_FakeDocument] | None = None) -> None:
        self._documents = documents

    async def asimilarity_search(self, query: str, k: int) -> list[_FakeDocument]:
        if self._documents is not None:
            return self._documents
        return [_FakeDocument(f"passage for {query!r} (k={k})")]


async def test_returns_empty_without_touching_store_when_corpus_not_ingested(tmp_path, monkeypatch):
    # No corpus has ever been ingested: the persist dir does not exist. The
    # embedding model (a multi-GB local load) must NOT be constructed just to
    # search an empty collection.
    missing_dir = tmp_path / "never-ingested"
    monkeypatch.setattr(
        vector_store_module,
        "get_settings",
        lambda: _settings(chroma_persist_dir=str(missing_dir)),
    )

    def exploding_get_vector_store():
        raise AssertionError("vector store must not be built when corpus is missing")

    monkeypatch.setattr(vector_store_module, "get_vector_store", exploding_get_vector_store)

    assert await retrieve_passages("ลิ้นซีด") == []


async def test_searches_store_when_corpus_dir_exists(tmp_path, monkeypatch):
    persist_dir = tmp_path / "chroma"
    persist_dir.mkdir()
    monkeypatch.setattr(
        vector_store_module,
        "get_settings",
        lambda: _settings(chroma_persist_dir=str(persist_dir)),
    )
    monkeypatch.setattr(vector_store_module, "get_vector_store", lambda: _FakeStore())

    passages = await retrieve_passages("ลิ้นซีด")

    assert passages == ["passage for 'ลิ้นซีด' (k=5)"]


async def test_passages_carry_book_page_paragraph_source_tags(tmp_path, monkeypatch):
    persist_dir = tmp_path / "chroma"
    persist_dir.mkdir()
    monkeypatch.setattr(
        vector_store_module,
        "get_settings",
        lambda: _settings(chroma_persist_dir=str(persist_dir)),
    )
    documents = [
        _FakeDocument(
            "ลิ้นซีดบ่งถึงธาตุน้ำพร่อง",
            {"book_id": "tamra-ttm", "book_title": "ตำราแพทย์แผนไทย", "page": 42, "paragraph": 3},
        ),
        _FakeDocument("ธาตุทั้งสี่", {"chapter": "ธาตุเจ้าเรือน", "section": "ธาตุดิน"}),
        _FakeDocument("chunk with no provenance"),
    ]
    monkeypatch.setattr(vector_store_module, "get_vector_store", lambda: _FakeStore(documents))

    passages = await retrieve_passages("ลิ้นซีด")

    assert passages == [
        "[ตำราแพทย์แผนไทย หน้า 42 ย่อหน้าที่ 3]\nลิ้นซีดบ่งถึงธาตุน้ำพร่อง",
        "[ธาตุเจ้าเรือน > ธาตุดิน]\nธาตุทั้งสี่",
        "chunk with no provenance",
    ]


@pytest.mark.parametrize("query", ["", "   "])
async def test_blank_query_still_returns_list(query, tmp_path, monkeypatch):
    monkeypatch.setattr(
        vector_store_module,
        "get_settings",
        lambda: _settings(chroma_persist_dir=str(tmp_path / "missing")),
    )

    def exploding_get_vector_store():
        raise AssertionError("vector store must not be built when corpus is missing")

    monkeypatch.setattr(vector_store_module, "get_vector_store", exploding_get_vector_store)

    assert await retrieve_passages(query) == []
