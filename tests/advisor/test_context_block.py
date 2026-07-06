from app.advisor.graph import _build_context_block
from app.advisor.prompts import SYSTEM_PROMPT


def test_context_block_puts_profile_before_records_and_rag():
    block = _build_context_block(
        retrieved_passages=["TTM passage"],
        recent_records_summary="record summary",
        health_profile_block="อายุ 27 ปี เพศชาย",
    )
    profile_pos = block.index("อายุ 27 ปี")
    records_pos = block.index("record summary")
    rag_pos = block.index("TTM passage")
    assert profile_pos < records_pos < rag_pos


def test_context_block_omits_profile_section_when_empty():
    block = _build_context_block(
        retrieved_passages=[], recent_records_summary="", health_profile_block=""
    )
    assert block == ""


def test_system_prompt_covers_profile_and_single_intake_question():
    assert "Health Profile" in SYSTEM_PROMPT
    assert "ONE" in SYSTEM_PROMPT
