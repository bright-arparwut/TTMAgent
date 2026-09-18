"""Unit test for scripts/thairepair.py -- the Thai combining-mark normalizer
(ticket #60, map #45; route established by #46).

The fixtures are real fragments of book three's `pdftotext -raw` output, captured
from the 41 MB PDF, so these assert against the actual defect rather than against a
hand-built imitation of it. They are short front-matter strings (a colophon line, a
title fragment, an index line), not monograph content.

The load-bearing case is `test_genuine_unmapped_char_survives`: exactly 3 `U+FFFD`
in the whole book are real characters the font failed to map, and a blind
`.replace("\ufffd", "")` would silently corrupt three words. `repair()` must leave
them standing while still dropping the 8,612 that are typographic furniture.
"""

from scripts.thairepair import repair, unmapped, validate

# `pdftotext -raw` output: every mark struck twice, plus the un-mapped stacking
# glyph after a stacked vowel+tone pair.
RAW_COLOPHON = "จัันทร์์เกษ ผู้้\ufffdอำำ\ufffdนวยการ"
CLEAN_COLOPHON = "จันทร์เกษ ผู้อำนวยการ"

RAW_TITLE = "ารใช้้ยาสมุุนไพร\nในก"
CLEAN_TITLE = "ารใช้ยาสมุนไพร\nในก"

# An index line whose `U+FFFD` is NOT preceded by a doubled mark: a genuine
# character the font lost. Printed, it reads `ค้นหาสาเหตุ`.
RAW_UNMAPPED = "ลตนเอง\n1. ค\ufffdนหาสาเหตุุของ"
CLEAN_UNMAPPED = "ลตนเอง\n1. ค\ufffdนหาสาเหตุของ"


def test_collapses_doubled_marks():
    assert repair(RAW_TITLE) == CLEAN_TITLE


def test_drops_stacking_glyph_after_doubled_mark():
    assert repair(RAW_COLOPHON) == CLEAN_COLOPHON
    assert "\ufffd" not in repair(RAW_COLOPHON)


def test_genuine_unmapped_char_survives():
    """The three real lost characters must not be swept up with the furniture."""
    assert repair(RAW_UNMAPPED) == CLEAN_UNMAPPED
    assert unmapped(repair(RAW_UNMAPPED)) == [len("ลตนเอง\n1. ค")]


def test_repair_is_idempotent():
    once = repair(RAW_COLOPHON)
    assert repair(once) == once


def test_clean_thai_is_untouched():
    """A legal vowel+tone stack is not a doubling and must survive."""
    for text in (CLEAN_COLOPHON, CLEAN_TITLE, "เบื้องต้น", "ข้อห้ามใช้"):
        assert repair(text) == text


def test_validate_reports_zero_on_repaired_text():
    metrics = validate(repair(RAW_COLOPHON + RAW_TITLE))
    assert metrics["doubled"] == 0
    assert metrics["illegal_above_pairs"] == 0
    assert metrics["unmapped"] == 0


def test_validate_sees_the_defect_before_repair():
    metrics = validate(RAW_COLOPHON + RAW_TITLE)
    assert metrics["doubled"] > 0
    assert metrics["illegal_above_pairs"] > 0
