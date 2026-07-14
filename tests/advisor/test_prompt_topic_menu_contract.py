"""The prompt half of the ADR 0006 delimiter contract: the format the
system prompt TEACHES must be the format the parser ACCEPTS. Changing
either side alone breaks the menu silently -- these tests fail loudly
instead."""

from app.advisor.prompts import SYSTEM_PROMPT
from app.advisor.topic_menu import TOPIC_MENU_MARKER, split_topic_menu


def test_prompt_teaches_the_exact_marker_the_parser_matches():
    assert TOPIC_MENU_MARKER in SYSTEM_PROMPT


def test_a_reply_in_the_prompts_taught_format_parses_into_topics():
    # Mirrors the example block shown in the system prompt verbatim.
    reply = (
        "ธาตุเจ้าเรือนของคุณน่าจะเป็นธาตุไฟค่ะ\n\n"
        f"{TOPIC_MENU_MARKER}\n- อาหารบำรุงธาตุ\n- ท่าบริหารแก้ปวดหลัง"
    )
    parsed = split_topic_menu(reply)
    assert parsed.visible_text == "ธาตุเจ้าเรือนของคุณน่าจะเป็นธาตุไฟค่ะ"
    assert parsed.topics == ("อาหารบำรุงธาตุ", "ท่าบริหารแก้ปวดหลัง")


def test_prompt_forbids_menus_on_red_flag_escalations():
    assert "NEVER attach a Topic Menu to a red-flag escalation" in SYSTEM_PROMPT
