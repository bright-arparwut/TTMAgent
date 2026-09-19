"""Unit test for scripts/extract_herbs_book.py (ticket #60, map #45).

Synthetic pages shaped like the real book. Two cases carry the findings that cost
the most to discover, so they are pinned here rather than left to a re-run:

- `test_name_comes_from_furniture_not_field_labels`: the herb's name and the
  numbered field labels are both `N. <thai>` at the start of a line, so a naive
  regex returns `ส่วนที่ใช้` for herb 2. Anchoring on the running title is what
  separates them.
- `test_monograph_without_prohibited_field_is_flagged`: three monographs carry no
  `ข้อห้ามใช้`, and one (ขลู่) carries no safety field at all. A gate that assumes
  presence fails open on exactly these, so the flags must be per-monograph facts
  rather than a book-wide count.
"""

from scripts.extract_herbs_book import (
    find_monograph_starts,
    page_records,
    parse_monograph,
    parse_symptom_index,
    split_pages,
)

RUNNING = "แนวทางการใช้ยาสมุนไพร\nในการดูแลอาการเจ็บป่วยเบื้องต้น"

MONOGRAPH = f"""1. ชื่อวิทยาศาสตร์ : Boesenbergia rotunda (L.) Mansf.
ชื่อพ้อง : B. pandurata (Roxb.) Schltr.
ชื่อวงศ์ : Zingiberaceae
ชื่อสามัญ : Fingerroot
ชื่อท้องถิ่น : กะแอน, ขิงทราย, ละแอน
2. ส่วนที่ใช้ รสและสรรพคุณยาไทย
ส่วนที่ใช้ : ราก และเหง้า
3. วิธีใช้
ข้อห้ามใช้ : -
คำเตือน : -
ข้อควรระวัง : ผู้หญิงในวัยเจริญพันธุ์
4. ลักษณะพืช
2. กระชาย
{RUNNING}
37
"""

# ขลู่: field 3 runs straight into field 4 with no safety block at all.
NO_SAFETY = f"""1. ชื่อวิทยาศาสตร์ : Pluchea indica (L.) Less.
ชื่อพ้อง : Baccharis indica L.
ชื่อวงศ์ : Asteraceae
ชื่อสามัญ : Indian marsh fleabane
ชื่อท้องถิ่น : คลู, ขลู
3. วิธีใช้
ขับปัสสาวะ แก้อาการขัดเบา
4. ลักษณะพืช
11. ขลู่
{RUNNING}
69
"""


def test_split_pages_uses_form_feeds():
    assert split_pages("a\fb\fc") == ["a", "b", "c"]


def test_find_monograph_starts_is_one_based():
    pages = ["front", MONOGRAPH, "middle", NO_SAFETY]
    assert find_monograph_starts(pages) == [2, 4]


def test_name_comes_from_furniture_not_field_labels():
    parsed = parse_monograph(MONOGRAPH, ordinal=2, pdf_start=45, pdf_end=48)
    assert parsed["name"] == "กระชาย"
    assert parsed["latin"] == "Boesenbergia rotunda (L.) Mansf."


def test_name_fields_are_captured():
    parsed = parse_monograph(MONOGRAPH, ordinal=2, pdf_start=45, pdf_end=48)
    assert parsed["family"] == "Zingiberaceae"
    assert parsed["common"] == "Fingerroot"
    assert parsed["local"] == "กะแอน, ขิงทราย, ละแอน"
    assert parsed["synonym"] == "B. pandurata (Roxb.) Schltr."


def test_printed_pages_are_pdf_pages_less_the_offset():
    parsed = parse_monograph(MONOGRAPH, ordinal=2, pdf_start=45, pdf_end=48)
    assert parsed["pages"] == [37, 40]
    assert parsed["pdf_pages"] == [45, 48]


def test_monograph_with_safety_fields_is_flagged():
    parsed = parse_monograph(MONOGRAPH, ordinal=2, pdf_start=45, pdf_end=48)
    assert (parsed["has_prohibited"], parsed["has_warning"], parsed["has_caution"]) == (
        True,
        True,
        True,
    )


def test_monograph_without_prohibited_field_is_flagged():
    parsed = parse_monograph(NO_SAFETY, ordinal=11, pdf_start=77, pdf_end=79)
    assert parsed["name"] == "ขลู่"
    assert not parsed["has_prohibited"]
    assert not parsed["has_warning"]
    assert not parsed["has_caution"]


def test_symptom_index_maps_sections_to_herbs():
    pages = [
        "1. ระบบทางเดินอาหาร\n"
        "1.1 ท้องอืด ท้องเฟ้อ ได้แก่ กระชาย\nกระเทียม กระวาน\n"
        "1.2 ท้องเดิน บิด ได้แก่ กระชาย ข่า\n",
        "3. ระบบทางเดินปัสสาวะ\n3.1 ขัดเบา ได้แก่ กระเจี๊ยบแดง ขลู่\nบทนำ\n" + RUNNING + "\n2\n",
    ]
    sections = parse_symptom_index(pages, span=(1, 2))
    assert [s["number"] for s in sections] == ["1.1", "1.2", "3.1"]
    assert sections[0]["title"] == "ท้องอืด ท้องเฟ้อ"
    # herb lists wrap across lines, so the continuation must be joined in
    assert sections[0]["herbs"] == ["กระชาย", "กระเทียม", "กระวาน"]
    assert sections[0]["group_title"] == "ระบบทางเดินอาหาร"
    assert sections[2]["group_title"] == "ระบบทางเดินปัสสาวะ"


def test_symptom_index_strips_page_furniture():
    """The last section on a page runs into the running title, folio and the
    chapter heading; none of those are herbs."""
    pages = [
        "3. ระบบทางเดินปัสสาวะ\n3.1 ขัดเบา ได้แก่ กระเจี๊ยบแดง ขลู่\nบทนำ\n" + RUNNING + "\n2\n",
        "",
    ]
    assert parse_symptom_index(pages, span=(1, 1))[0]["herbs"] == ["กระเจี๊ยบแดง", "ขลู่"]


def test_page_records_carry_both_page_numbers():
    records = page_records(["", "front matter", MONOGRAPH])
    assert [r["pdf_page"] for r in records] == [2, 3]
    assert [r["page"] for r in records] == [-6, -5]
    assert records[0]["book_id"] == "herbs-50"
    assert records[0]["paragraph"] == 1


def test_blank_pages_are_skipped():
    assert page_records(["", "   \n ", "real"]) == [
        {
            "book_id": "herbs-50",
            "book_title": "แนวทางการใช้ยาสมุนไพรในการดูแลอาการเจ็บป่วยเบื้องต้น",
            "page": -5,
            "pdf_page": 3,
            "paragraph": 1,
            "text": "real",
        }
    ]
