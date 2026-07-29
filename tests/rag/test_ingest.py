import json

from app.rag.ingest import CHUNK_SIZE, load_jsonl


def _write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _record(page: int, paragraph: int, text: str) -> dict:
    return {
        "book_id": "tamra-ttm",
        "book_title": "ตำราแพทย์แผนไทย",
        "page": page,
        "pdf_page": page + 10,
        "paragraph": paragraph,
        "text": text,
    }


def test_one_document_per_paragraph_with_provenance_and_deterministic_ids(tmp_path):
    jsonl = tmp_path / "book.jsonl"
    _write_jsonl(
        jsonl,
        [
            _record(42, 1, "ลิ้นซีดบ่งถึงธาตุน้ำพร่อง"),
            _record(42, 2, "ให้บำรุงด้วยอาหารรสเปรี้ยว 酸味"),
        ],
    )

    documents, ids = load_jsonl(jsonl)

    assert ids == ["tamra-ttm:p42:para1", "tamra-ttm:p42:para2"]
    assert [d.page_content for d in documents] == [
        "ลิ้นซีดบ่งถึงธาตุน้ำพร่อง",
        "ให้บำรุงด้วยอาหารรสเปรี้ยว 酸味",
    ]
    assert documents[0].metadata == {
        "book_id": "tamra-ttm",
        "book_title": "ตำราแพทย์แผนไทย",
        "page": 42,
        "paragraph": 1,
    }


def test_oversized_paragraph_splits_but_every_piece_keeps_provenance(tmp_path):
    jsonl = tmp_path / "book.jsonl"
    long_text = " ".join(f"คำที่{i}" for i in range(CHUNK_SIZE))  # far beyond one chunk
    _write_jsonl(jsonl, [_record(7, 1, long_text)])

    documents, ids = load_jsonl(jsonl)

    assert len(documents) > 1
    assert ids == [f"tamra-ttm:p7:para1:c{i}" for i in range(1, len(documents) + 1)]
    assert all(d.metadata["page"] == 7 and d.metadata["paragraph"] == 1 for d in documents)


def test_blank_lines_are_skipped(tmp_path):
    jsonl = tmp_path / "book.jsonl"
    jsonl.write_text(
        json.dumps(_record(1, 1, "ย่อหน้าเดียว"), ensure_ascii=False) + "\n\n\n",
        encoding="utf-8",
    )

    documents, ids = load_jsonl(jsonl)

    assert len(documents) == 1
    assert ids == ["tamra-ttm:p1:para1"]
