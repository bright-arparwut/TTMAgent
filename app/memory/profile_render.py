"""Render the Health Profile face sheet for prompt injection (ADR 0003).

One renderer serves both consumers: the Profile Updater needs the stable
[id] labels to emit patches against, and the Advisor needs the current
facts plus the missing-field hints that drive natural intake questions.
"""

from datetime import date

from app.memory.element import age_years, derive_element
from app.models.profile import HealthProfile, ProfileItem

_SECTIONS: list[tuple[str, str]] = [
    ("chronic_conditions", "โรคประจำตัว"),
    ("allergies", "ประวัติแพ้"),
    ("medications", "ยา/สมุนไพรที่ใช้ประจำ"),
    ("habits", "พฤติกรรม"),
    ("ongoing_complaints", "อาการที่ติดตามอยู่"),
]


def _render_items(items: list[ProfileItem]) -> str:
    return " · ".join(
        f"[{item.id}] {item.text} (บันทึก {item.noted_at.date().isoformat()})"
        for item in items
    )


def render_profile(profile: HealthProfile, *, today: date) -> str:
    header_parts: list[str] = []
    missing: list[str] = []

    if profile.birth_date is not None:
        header_parts.append(f"อายุ {age_years(profile.birth_date, today=today)} ปี")
        header_parts.append(f"ธาตุเจ้าเรือน: {derive_element(profile.birth_date)}")
    else:
        missing.append("วันเกิด (ใช้คำนวณธาตุเจ้าเรือน)")

    if profile.sex:
        header_parts.append(f"เพศ {profile.sex}")
    else:
        missing.append("เพศ")

    lines: list[str] = []
    if header_parts:
        lines.append(" ".join(header_parts))

    has_items = False
    for field, label in _SECTIONS:
        items = getattr(profile, field)
        if items:
            has_items = True
            lines.append(f"{label}: {_render_items(items)}")

    if profile.notes:
        lines.append(f"หมายเหตุ: {profile.notes}")

    if not header_parts and not has_items and not profile.notes:
        lines.append("ยังไม่มีข้อมูลในแฟ้มผู้ใช้รายนี้")

    if missing:
        lines.append(f"ข้อมูลที่ยังขาด (ถามเมื่อเหมาะสม): {', '.join(missing)}")

    return "\n".join(lines)
