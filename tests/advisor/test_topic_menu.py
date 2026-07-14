"""The parser half of the ADR 0006 delimiter contract. The prompt half is
pinned by tests/advisor/test_prompt_topic_menu_contract.py."""

from app.advisor.topic_menu import (
    MAX_TOPIC_CHARS,
    MAX_TOPICS,
    TOPIC_MENU_MARKER,
    ParsedReply,
    split_topic_menu,
)

REPLY_BODY = "ธาตุเจ้าเรือนของคุณน่าจะเป็นธาตุไฟค่ะ ควรหลีกเลี่ยงของทอดและของเผ็ดจัด"


def test_reply_without_marker_passes_through_unchanged():
    parsed = split_topic_menu(REPLY_BODY)
    assert parsed == ParsedReply(raw_text=REPLY_BODY, visible_text=REPLY_BODY, topics=())


def test_dash_bullet_block_is_split_into_visible_text_and_topics():
    raw = f"{REPLY_BODY}\n\n{TOPIC_MENU_MARKER}\n- อาหารบำรุงธาตุไฟ\n- ท่าบริหารตอนเช้า"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == REPLY_BODY
    assert parsed.topics == ("อาหารบำรุงธาตุไฟ", "ท่าบริหารตอนเช้า")
    assert parsed.raw_text == raw  # Working Buffer stores the block too


def test_bullet_and_numbered_items_are_accepted():
    raw = f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n• หัวข้อหนึ่ง\n1. หัวข้อสอง\n2) หัวข้อสาม\n* หัวข้อสี่"
    parsed = split_topic_menu(raw)
    assert parsed.topics == ("หัวข้อหนึ่ง", "หัวข้อสอง", "หัวข้อสาม", "หัวข้อสี่")


def test_bare_lines_after_marker_count_as_topics():
    raw = f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\nหัวข้อหนึ่ง\nหัวข้อสอง"
    parsed = split_topic_menu(raw)
    assert parsed.topics == ("หัวข้อหนึ่ง", "หัวข้อสอง")


def test_topics_are_capped_at_max_topics():
    items = "\n".join(f"- หัวข้อ{n}" for n in range(1, 8))
    parsed = split_topic_menu(f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n{items}")
    assert len(parsed.topics) == MAX_TOPICS
    assert parsed.topics[0] == "หัวข้อ1"


def test_long_topics_are_truncated_to_line_label_cap():
    long_topic = "ก" * 30
    parsed = split_topic_menu(f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n- {long_topic}")
    assert parsed.topics == ("ก" * MAX_TOPIC_CHARS,)


def test_marker_with_trailing_colon_and_whitespace_is_accepted():
    raw = f"{REPLY_BODY}\n  {TOPIC_MENU_MARKER}:  \n- หัวข้อหนึ่ง"
    assert split_topic_menu(raw).topics == ("หัวข้อหนึ่ง",)


def test_marker_mentioned_mid_sentence_is_not_a_block():
    raw = f"คำว่า {TOPIC_MENU_MARKER} เป็นเพียงตัวอย่างค่ะ"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == raw
    assert parsed.topics == ()


def test_marker_without_items_is_stripped_and_yields_no_topics():
    raw = f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == REPLY_BODY
    assert parsed.topics == ()


def test_menu_only_reply_degrades_to_full_raw_text():
    # An empty visible text would be rejected by LINE; degrade to the raw reply.
    raw = f"{TOPIC_MENU_MARKER}\n- หัวข้อหนึ่ง"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == raw
    assert parsed.topics == ()


def test_last_standalone_marker_wins():
    raw = (
        f"{TOPIC_MENU_MARKER}\nข้อความอธิบายรูปแบบ\n{REPLY_BODY}\n"
        f"{TOPIC_MENU_MARKER}\n- หัวข้อจริง"
    )
    parsed = split_topic_menu(raw)
    assert parsed.topics == ("หัวข้อจริง",)
    assert parsed.visible_text.endswith(REPLY_BODY)
