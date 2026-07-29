"""The prompt half of the citation-line contract: the format the system
prompt TEACHES must be the format the parser ACCEPTS (same philosophy as
the ADR 0006 topic-menu contract tests)."""

import re

from app.advisor.citation import split_citation
from app.advisor.prompts import SYSTEM_PROMPT


def _prompt_example_citation_line() -> str:
    # The example is shown quoted in the prompt; extract it exactly as the
    # LLM will see it so the real example cannot drift without failing here.
    match = re.search(r'"(\(อ้างอิง:[^"]*\))"', SYSTEM_PROMPT)
    assert match, "prompt no longer shows a quoted (อ้างอิง: ...) example"
    return match.group(1)


def test_the_prompts_own_example_line_parses_as_a_citation():
    example = _prompt_example_citation_line()
    body, citation = split_citation(f"คำตอบหลัก\n{example}")
    assert body == "คำตอบหลัก"
    assert citation is not None


def test_prompt_orders_the_citation_before_the_topic_menu_block():
    assert "BEFORE the [หัวข้อ] block" in SYSTEM_PROMPT


def test_prompt_forbids_invented_citations():
    assert "never invent a book, page, or paragraph number" in SYSTEM_PROMPT
