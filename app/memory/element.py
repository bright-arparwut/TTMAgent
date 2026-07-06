"""ธาตุเจ้าเรือน derivation -- deterministic code, never LLM-set (ADR 0003).

PROVISIONAL DOMAIN DATA: the month assignments below are a commonly
published simplification (Gregorian months). They MUST be confirmed
against the TTM corpus before the thesis evaluation. The contract that
code and tests rely on is structural only: all 12 months covered,
exactly the four elements.
"""

from datetime import date

MONTH_TO_ELEMENT: dict[int, str] = {
    11: "ดิน", 12: "ดิน", 1: "ดิน",
    8: "น้ำ", 9: "น้ำ", 10: "น้ำ",
    5: "ลม", 6: "ลม", 7: "ลม",
    2: "ไฟ", 3: "ไฟ", 4: "ไฟ",
}


def derive_element(birth_date: date) -> str:
    return MONTH_TO_ELEMENT[birth_date.month]


def age_years(birth_date: date, *, today: date) -> int:
    had_birthday = (today.month, today.day) >= (birth_date.month, birth_date.day)
    return today.year - birth_date.year - (0 if had_birthday else 1)
