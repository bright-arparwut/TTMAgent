"""Unit tests for scripts/build_herbs_notes.py (ticket #62, map #45).

Synthetic pages shaped like the real book. The cases that carry findings which
cost something to discover are pinned here rather than left to a re-run:

- `test_advice_subitems_are_not_section_headings`: printed p.21 carries `1.1`,
  `1.2` and `2.1`-`2.4` as advice sub-items *inside* sections 4.4 and 4.5. They
  are identical in shape to a real section heading, and only the 1.1 ... 6.4
  sequence tells them apart. Without the filter the book has 40 sections.
- `test_a_numbered_body_line_at_the_foot_of_a_page_survives`: the page header
  (`1. ระบบทางเดินอาหาร`, `1. กระเจี๊ยบแดง`) and an advice item (`4. ...`) are
  both `N. <thai>`. Only position -- directly above the running title --
  separates furniture from content.
- `test_monograph_stops_at_field_seven`: fields 7-9 are dropped (#50 decision F),
  and field 6 (`ข้อมูลการใช้เป็นอาหาร และคุณค่าทางโภชนาการ`) is kept.
- `test_range_names_what_the_note_transcribes`: a page that contributes no text
  after the cut is not in `pages`, because the filename is the citation (#51).
"""

import pytest

from scripts.build_herbs_notes import (
    MONOGRAPH_SPAN,
    SECTION_SPAN,
    Cut,
    Note,
    find_dropped_field,
    find_sections,
    format_section_body,
    slice_body,
    strip_furniture,
)

RUNNING = "แนวทางการใช้ยาสมุนไพร\nในการดูแลอาการเจ็บป่วยเบื้องต้น"


def pages_over(span: tuple[int, int], filled: dict[int, str]) -> dict[int, str]:
    """Every page in `span`, blank unless `filled` gives it text."""
    return {page: filled.get(page, "") for page in range(span[0], span[1] + 1)}


def footer(page: int, header: str | None = None) -> str:
    return ("" if header is None else header + "\n") + f"{RUNNING}\n{page}"


# --- furniture --------------------------------------------------------------


def test_running_title_folio_and_page_header_are_stripped():
    text = f"เนื้อหา\n{footer(34, '1. กระเจี๊ยบแดง')}"
    assert strip_furniture(text) == "เนื้อหา"


def test_a_numbered_body_line_at_the_foot_of_a_page_survives():
    # No running title below it, so `4. ...` is the last line of the advice list.
    text = "3. ดื่มน้ำสะอาด\n4. ในรายที่มีอาการผิดปกติอื่นร่วมด้วย"
    assert strip_furniture(text).endswith("4. ในรายที่มีอาการผิดปกติอื่นร่วมด้วย")


def test_page_header_directly_above_the_running_title_is_furniture():
    kept = strip_furniture(f"4. ในรายที่มีอาการ\n{footer(3, '1. ระบบทางเดินอาหาร')}")
    assert kept == "4. ในรายที่มีอาการ"


# --- section boundaries -----------------------------------------------------


def test_advice_subitems_are_not_section_headings():
    pages = pages_over(
        SECTION_SPAN,
        {
            3: "1.1\tท้องอืด\nเนื้อหา",
            5: "1.2\tท้องเดิน\nเนื้อหา",
            13: "2.1\tไอ ขับเสมหะ\nเนื้อหา",
            17: "3.1\tขัดเบา\nเนื้อหา",
            18: "4.1\tโรคกลากเกลื้อน\nเนื้อหา",
            19: "4.2\tฝี แผลพุพอง\n4.3\tแผลสด\nเนื้อหา",
            20: "4.4\tเลือดออก ห้ามเลือด\nเนื้อหา",
            # The real p.21: sub-items that restart at 1.1, inside section 4.4.
            21: "1.1 ใน 24 ชั่วโมงแรก ใช้น้ำแข็ง\n2.1 ชะล้างแผล\n4.5\tอักเสบแพ้จากแมลงกัดต่อย",
        },
    )
    numbers = [number for number, _, _, _ in find_sections(pages)]
    assert numbers == [(1, 1), (1, 2), (2, 1), (3, 1), (4, 1), (4, 2), (4, 3), (4, 4), (4, 5)]


def test_a_new_group_must_start_at_one():
    pages = pages_over(SECTION_SPAN, {3: "1.1\tก\n2.3\tข\n2.1\tค"})
    assert [n for n, _, _, _ in find_sections(pages)] == [(1, 1), (2, 1)]


# --- monograph boundaries ---------------------------------------------------


def test_monograph_stops_at_field_seven():
    body = (
        "1. ชื่อวิทยาศาสตร์ : Hibiscus sabdariffa L.\n"
        "6. ข้อมูลการใช้เป็นอาหาร และคุณค่าทางโภชนาการ\n"
        "คุณค่าทางโภชนาการ 100 กรัม\n"
        "7. องค์ประกอบทางเคมี\n"
        "สารกลุ่มพอลิแซ็กคาไรด์"
    )
    pages = pages_over(MONOGRAPH_SPAN, {34: body})
    end_page, end_char = find_dropped_field(pages, (34, 0), 34)
    kept = pages[end_page][:end_char]
    assert "6. ข้อมูลการใช้เป็นอาหาร" in kept
    assert "องค์ประกอบทางเคมี" not in kept


def test_field_seven_on_a_later_page_still_ends_the_cut():
    pages = pages_over(MONOGRAPH_SPAN, {34: "1. ชื่อวิทยาศาสตร์ : X", 35: "7. องค์ประกอบทางเคมี"})
    assert find_dropped_field(pages, (34, 0), 35) == (35, 0)


# --- body rendering ---------------------------------------------------------


def test_dingbat_headings_become_subheadings():
    rendered = format_section_body(" คำแนะนำเพื่อการดูแลตนเอง\n1. พักผ่อน")
    assert "## คำแนะนำเพื่อการดูแลตนเอง" in rendered
    assert " " not in rendered


def test_herb_table_becomes_markdown_with_a_separator_row():
    rendered = format_section_body(
        "3 การรักษาด้วยสมุนไพรเดี่ยว\nลำดับ ชื่อสมุนไพร หน้าที่\n1 กระชาย 37\n2 ข่า 74"
    )
    lines = [line for line in rendered.splitlines() if line.startswith("|")]
    assert lines[0] == "| ลำดับ | ชื่อสมุนไพร | หน้าที่ |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2:] == ["| 1 | กระชาย | 37 |", "| 2 | ข่า | 74 |"]


def test_table_split_across_pages_renders_one_table():
    rendered = format_section_body(
        "ลำดับ ชื่อสมุนไพร หน้าที่\n1 กระชาย 37\nลำดับ ชื่อสมุนไพร หน้าที่\n2 ข่า 74"
    )
    assert rendered.count("| --- | --- | --- |") == 1
    assert rendered.count("| ลำดับ | ชื่อสมุนไพร | หน้าที่ |") == 1


# --- page markers and ranges ------------------------------------------------


def test_page_markers_mark_transitions_only():
    pages = {34: f"หนึ่ง\n{footer(34)}", 35: f"สอง\n{footer(35)}"}
    body, covered = slice_body(pages, Cut(34, 0, 35, len(pages[35])), section=False)
    assert covered == (34, 35)
    assert "<!-- p.34 -->" not in body
    assert body.splitlines() == ["หนึ่ง", "<!-- p.35 -->", "สอง"]


def test_range_names_what_the_note_transcribes():
    # Field 7 opens p.36, so the cut takes nothing from it and p.36 is not cited.
    pages = {34: f"หนึ่ง\n{footer(34)}", 35: f"สอง\n{footer(35)}", 36: "7. องค์ประกอบทางเคมี"}
    body, covered = slice_body(pages, Cut(34, 0, 36, 0), section=False)
    assert covered == (34, 35)
    assert "p.36" not in body


def test_a_page_of_pure_furniture_contributes_nothing():
    pages = {34: f"หนึ่ง\n{footer(34)}", 35: footer(35)}
    _, covered = slice_body(pages, Cut(34, 0, 35, len(pages[35])), section=False)
    assert covered == (34, 34)


# --- the note itself --------------------------------------------------------


@pytest.mark.parametrize(
    ("ordinal", "expected"),
    [(301, "herbs-50-301"), (340, "herbs-50-340")],
)
def test_uid_is_zero_padded_to_three_digits(ordinal, expected):
    assert Note(ordinal, "ch", "sec", "body", (3, 4)).uid == expected


def test_filename_is_the_citation():
    note = Note(302, "ระบบทางเดินอาหาร", "ท้องเดิน (Diarrhea)", "body", (5, 5))
    assert note.filename == "302-ท้องเดิน (Diarrhea)-น.5-5.md"
    assert note.pdf_pages == (13, 13)
