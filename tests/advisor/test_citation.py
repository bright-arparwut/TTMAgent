from app.advisor.citation import inline_citation, split_citation
from app.advisor.topic_menu import split_topic_menu


def test_splits_trailing_citation_line():
    text = "ลิ้นมีรอยแตกมักแสดงถึงการขาดเลือด\n\n(อ้างอิง: ตำราลิ้น หน้า 98 ย่อหน้าที่ 3)"

    body, citation = split_citation(text)

    assert body == "ลิ้นมีรอยแตกมักแสดงถึงการขาดเลือด"
    assert citation == "ตำราลิ้น หน้า 98 ย่อหน้าที่ 3"


def test_no_citation_line_returns_text_untouched():
    text = "คำตอบธรรมดา (มีวงเล็บกลางประโยค) จบ"
    assert split_citation(text) == (text, None)


def test_citation_must_be_the_last_line():
    # A citation-shaped line in the middle of the reply is body text.
    text = "(อ้างอิง: ตำรา หน้า 1 ย่อหน้าที่ 1)\nแต่บรรทัดสุดท้ายคือคำตอบ"
    assert split_citation(text) == (text, None)


def test_citation_only_reply_degrades_to_untouched_text():
    # Stripping the citation must never produce an empty LINE message.
    text = "(อ้างอิง: ตำรา หน้า 1 ย่อหน้าที่ 1)"
    assert split_citation(text) == (text, None)


def test_inline_citation_round_trips():
    body, citation = split_citation("คำตอบ\n\n(อ้างอิง: ตำรา หน้า 5 ย่อหน้าที่ 2)")
    assert inline_citation(body, citation) == "คำตอบ\n\n(อ้างอิง: ตำรา หน้า 5 ย่อหน้าที่ 2)"
    assert inline_citation("คำตอบ", None) == "คำตอบ"


def test_citation_before_topic_menu_splits_cleanly_through_both_parsers():
    # The documented order: body, source line, then the menu block.
    raw = (
        "ลิ้นซีดบ่งถึงเลือดพร่อง ควรพักผ่อนให้เพียงพอ\n"
        "(อ้างอิง: ตำราลิ้น หน้า 42 ย่อหน้าที่ 1)\n"
        "[หัวข้อ]\n- อาหารบำรุงเลือด\n- ท่านวดกระตุ้น"
    )

    parsed = split_topic_menu(raw)
    body, citation = split_citation(parsed.visible_text)

    assert parsed.topics == ("อาหารบำรุงเลือด", "ท่านวดกระตุ้น")
    assert body == "ลิ้นซีดบ่งถึงเลือดพร่อง ควรพักผ่อนให้เพียงพอ"
    assert citation == "ตำราลิ้น หน้า 42 ย่อหน้าที่ 1"


def test_misordered_citation_after_menu_block_never_becomes_a_button():
    raw = "ลิ้นซีดบ่งถึงเลือดพร่อง\n[หัวข้อ]\n- อาหารบำรุงเลือด\n(อ้างอิง: ตำราลิ้น หน้า 42 ย่อหน้าที่ 1)"

    parsed = split_topic_menu(raw)

    assert parsed.topics == ("อาหารบำรุงเลือด",)
