"""Unit tests for app.rag.corpus_merge (ADR 0008 JSONL assembly)."""

import json

from app.rag.corpus_merge import (
    PageFile,
    assign_printed_pages,
    front_matter_records,
    load_page_files,
    offset_changes,
    split_runs,
    to_records,
    validate_records,
)


def page(pdf_page, printed, paragraphs):
    return PageFile(pdf_page=pdf_page, printed_page_number=printed, paragraphs=paragraphs)


def test_split_runs_separates_leading_and_trailing_unnumbered_pages():
    pages = [
        page(1, None, ["ปกหน้า"]),
        page(2, None, []),
        page(3, 1, ["บทที่หนึ่ง"]),
        page(4, None, ["หน้าไม่มีเลขกลางเล่ม"]),
        page(5, 3, ["เนื้อหา"]),
        page(6, None, ["ปกหลัง"]),
    ]
    front, body, back = split_runs(pages)
    assert [p.pdf_page for p in front] == [1, 2]
    assert [p.pdf_page for p in body] == [3, 4, 5]
    assert [p.pdf_page for p in back] == [6]


def test_split_runs_without_first_body_pdf_page_keeps_current_guessing_behavior():
    pages = [
        page(1, None, ["ปกหน้า"]),
        page(2, 1, ["บทที่หนึ่ง"]),
        page(3, 2, ["เนื้อหา"]),
    ]
    front, body, back = split_runs(pages)
    assert [p.pdf_page for p in front] == [1]
    assert [p.pdf_page for p in body] == [2, 3]
    assert back == []


def test_split_runs_with_first_body_pdf_page_keeps_unnumbered_chapter_opener_in_body():
    pages = [
        page(1, None, ["ปกหน้า"]),
        page(2, None, ["หน้าปกใน"]),
        page(3, None, ["บทที่ 1 เปิดบทไม่มีเลขหน้า"]),
        page(4, 2, ["เนื้อหาต่อ"]),
        page(5, None, ["ปกหลัง"]),
    ]
    front, body, back = split_runs(pages, first_body_pdf_page=3)
    assert [p.pdf_page for p in front] == [1, 2]
    assert [p.pdf_page for p in body] == [3, 4]
    assert [p.pdf_page for p in back] == [5]

    # The unnumbered opener anchors to the following numbered page's offset.
    assigned = assign_printed_pages(body)
    assert [(pdf, printed) for pdf, printed, _ in assigned] == [(3, 1), (4, 2)]


def test_assign_printed_pages_uses_printed_number_and_interpolates_within_a_run():
    body = [page(10, 15, ["ก"]), page(11, None, ["ข"]), page(12, 17, ["ค"])]
    assigned = assign_printed_pages(body)
    assert [(pdf, printed) for pdf, printed, _ in assigned] == [(10, 15), (11, 16), (12, 17)]


def test_assign_printed_pages_anchors_a_gap_straddling_page_to_the_following_run():
    body = [page(52, 74, ["ก"]), page(53, None, ["เปิดบท"]), page(54, 86, ["ข"])]
    assigned = assign_printed_pages(body)
    assert [(pdf, printed) for pdf, printed, _ in assigned] == [(52, 74), (53, 85), (54, 86)]


def test_assign_printed_pages_interpolates_from_following_when_no_preceding_number():
    body = [page(3, None, ["เปิดบท"]), page(4, 2, ["เนื้อหา"])]
    assigned = assign_printed_pages(body)
    assert [(pdf, printed) for pdf, printed, _ in assigned] == [(3, 1), (4, 2)]


def test_to_records_numbers_paragraphs_per_page_and_uses_adr_key_order():
    assigned = [(3, 1, ["หัวข้อ", "ย่อหน้า"]), (4, 2, ["ต่อ"])]
    records = to_records(assigned, book_id="b", book_title="ชื่อ")
    assert [r["paragraph"] for r in records] == [1, 2, 1]
    expected_keys = [
        "book_id",
        "book_title",
        "page",
        "pdf_page",
        "paragraph",
        "text",
    ]
    assert list(records[0].keys()) == expected_keys
    assert records[2] == {
        "book_id": "b",
        "book_title": "ชื่อ",
        "page": 2,
        "pdf_page": 4,
        "paragraph": 1,
        "text": "ต่อ",
    }


def test_to_records_skips_blank_pages_and_whitespace_paragraphs():
    assigned = [(3, 1, []), (4, 2, ["  ", "จริง"])]
    records = to_records(assigned, book_id="b", book_title="ชื่อ")
    assert [(r["pdf_page"], r["paragraph"], r["text"]) for r in records] == [(4, 1, "จริง")]


def test_validate_records_passes_clean_records():
    records = to_records([(3, 1, ["ก", "ข"])], book_id="b", book_title="ชื่อ")
    assert validate_records(records, book_id="b", book_title="ชื่อ") == []


def test_validate_records_flags_empty_text_bad_keys_and_gaps():
    bad = [
        {
            "book_id": "b",
            "book_title": "ชื่อ",
            "page": 1,
            "pdf_page": 3,
            "paragraph": 1,
            "text": "",
        },
        {
            "book_id": "b",
            "book_title": "ชื่อ",
            "page": 1,
            "pdf_page": 3,
            "paragraph": 3,
            "text": "ข",
        },
        {
            "book_id": "x",
            "book_title": "ชื่อ",
            "page": 1,
            "pdf_page": 4,
            "paragraph": 1,
            "text": "ค",
        },
        {
            "book_id": "b",
            "book_title": "ชื่อ",
            "page": 1,
            "pdf_page": 5,
            "paragraph": 1,
            "text": "ง",
            "extra": 1,
        },
    ]
    errors = validate_records(bad, book_id="b", book_title="ชื่อ")
    assert any("empty text" in e for e in errors)
    assert any("paragraph" in e for e in errors)  # 1 then 3: not contiguous
    assert any("keys" in e for e in errors)
    assert any("book_id mismatch" in e and "x" in e for e in errors)


def test_validate_records_book_title_mismatch_names_the_field_and_value():
    records = [
        {
            "book_id": "b",
            "book_title": "ผิด",
            "page": 1,
            "pdf_page": 3,
            "paragraph": 1,
            "text": "ก",
        }
    ]
    errors = validate_records(records, book_id="b", book_title="ถูก")
    assert any("book_title mismatch" in e and "ผิด" in e for e in errors)


def test_validate_records_flags_non_int_and_non_str_fields():
    records = [
        {
            "book_id": "b",
            "book_title": "ชื่อ",
            "page": "1",
            "pdf_page": 3,
            "paragraph": 1,
            "text": "ก",
        },
        {
            "book_id": "b",
            "book_title": "ชื่อ",
            "page": 1,
            "pdf_page": 3,
            "paragraph": 1,
            "text": 5,
        },
    ]
    errors = validate_records(records, book_id="b", book_title="ชื่อ")
    assert any("page" in e and "int" in e for e in errors)
    assert any("text" in e and "str" in e for e in errors)


def test_validate_records_flags_duplicate_chunk_ids_when_pages_collide():
    # Two pdf pages resolving to the same printed page must not validate clean:
    # their chunk ids (<book_id>:p<page>:para<paragraph>) collide and silently
    # overwrite each other in Chroma.
    records = to_records([(40, 30, ["ก", "ข"]), (41, 30, ["ค"])], book_id="b", book_title="t")
    errors = validate_records(records, book_id="b", book_title="t")
    assert any("duplicate" in e and "b:p30:para1" in e for e in errors)


def test_validate_records_flags_page_going_backwards():
    records = [
        {"book_id": "b", "book_title": "ชื่อ", "page": 9, "pdf_page": 3, "paragraph": 1, "text": "ก"},
        {"book_id": "b", "book_title": "ชื่อ", "page": 7, "pdf_page": 4, "paragraph": 1, "text": "ข"},
    ]
    errors = validate_records(records, book_id="b", book_title="ชื่อ")
    assert any("decreas" in e for e in errors)


def test_offset_changes_reports_change_points_only():
    body = [page(10, 15, ["ก"]), page(11, 16, ["ข"]), page(12, 18, ["ค"])]
    changes = offset_changes(body)
    assert len(changes) == 1
    assert "pdf_page 12" in changes[0]


def test_front_matter_records_set_page_equal_to_pdf_page_and_front_book_id():
    front = [page(1, None, ["ปกหน้า"]), page(2, None, ["หน้าปกใน"])]
    back = [page(9, None, ["ปกหลัง"])]
    records = front_matter_records(front, back, book_id="b", book_title="ชื่อ")
    assert len(records) == 3
    assert all(r["page"] == r["pdf_page"] for r in records)
    assert all(r["book_id"] == "b-front" for r in records)
    assert all(r["book_title"] == "ชื่อ" for r in records)


def test_load_page_files_reports_bad_printed_page_number_type_as_unreadable(tmp_path):
    (tmp_path / "p001.json").write_text(
        json.dumps({"printed_page_number": "5", "paragraphs": ["ก"]}), encoding="utf-8"
    )
    pages, errors = load_page_files(tmp_path, 1)
    assert pages == []
    assert any("p001.json" in e for e in errors)


def test_load_page_files_accepts_int_or_null_printed_page_number(tmp_path):
    (tmp_path / "p001.json").write_text(
        json.dumps({"printed_page_number": None, "paragraphs": ["ก"]}), encoding="utf-8"
    )
    (tmp_path / "p002.json").write_text(
        json.dumps({"printed_page_number": 3, "paragraphs": ["ข"]}), encoding="utf-8"
    )
    pages, errors = load_page_files(tmp_path, 2)
    assert errors == []
    assert [p.printed_page_number for p in pages] == [None, 3]
