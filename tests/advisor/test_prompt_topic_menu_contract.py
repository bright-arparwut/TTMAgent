"""The prompt half of the ADR 0006 delimiter contract: the format the
system prompt TEACHES must be the format the parser ACCEPTS. Changing
either side alone breaks the menu silently -- these tests fail loudly
instead."""

from app.advisor.prompts import SYSTEM_PROMPT
from app.advisor.topic_menu import TOPIC_MENU_MARKER, split_topic_menu


def test_prompt_shows_the_marker_as_a_standalone_line():
    # The parser only accepts the marker on its own line (_last_marker_line),
    # so the prompt must display it the same way -- a substring match would
    # keep passing even if the example collapsed into running prose.
    assert any(line.strip() == TOPIC_MENU_MARKER for line in SYSTEM_PROMPT.splitlines())


def test_the_prompts_own_example_block_parses_into_its_topics():
    # Extract the example block exactly as the LLM will see it: the marker
    # line plus its run of bullet lines. Hardcoding a copy here would let
    # the prompt's real example drift without failing this test.
    lines = SYSTEM_PROMPT.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == TOPIC_MENU_MARKER)
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip().startswith("-"):
            break
        block.append(line)
    reply = "คำตอบหลัก\n" + "\n".join(block)

    parsed = split_topic_menu(reply)

    assert parsed.visible_text == "คำตอบหลัก"
    assert parsed.topics == ("อาหารบำรุงธาตุ", "ท่าบริหารแก้ปวดหลัง")


def test_prompt_forbids_menus_on_red_flag_escalations():
    assert "NEVER attach a Topic Menu to a red-flag escalation" in SYSTEM_PROMPT
