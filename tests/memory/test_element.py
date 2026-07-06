from datetime import date

from app.memory.element import MONTH_TO_ELEMENT, age_years, derive_element

VALID_ELEMENTS = {"ดิน", "น้ำ", "ลม", "ไฟ"}


def test_mapping_covers_all_twelve_months_with_valid_elements():
    assert sorted(MONTH_TO_ELEMENT) == list(range(1, 13))
    assert set(MONTH_TO_ELEMENT.values()) == VALID_ELEMENTS


def test_derive_element_uses_birth_month():
    assert derive_element(date(1998, 11, 2)) == MONTH_TO_ELEMENT[11]


def test_age_years_counts_completed_years_only():
    assert age_years(date(1998, 11, 2), today=date(2026, 7, 6)) == 27
    assert age_years(date(1998, 11, 2), today=date(2026, 11, 2)) == 28
