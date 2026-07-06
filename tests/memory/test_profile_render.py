from datetime import UTC, date, datetime

from app.memory.health_profile import empty_profile
from app.memory.profile_render import render_profile
from app.models.profile import HealthProfile, ProfileItem

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
TODAY = date(2026, 7, 6)


def test_empty_profile_renders_missing_field_hints():
    text = render_profile(empty_profile("U1", NOW), today=TODAY)
    assert "ยังไม่มีข้อมูล" in text
    assert "วันเกิด" in text
    assert "เพศ" in text


def test_full_profile_renders_ids_element_age_and_provenance():
    profile = HealthProfile(
        user_id="U1",
        sex="ชาย",
        birth_date=date(1998, 11, 2),
        allergies=[ProfileItem(id="a1", text="แพ้อาหารทะเล (กุ้ง)", noted_at=NOW)],
        habits=[ProfileItem(id="h1", text="นอนดึกตี 1-2", noted_at=NOW)],
        id_counters={"allergies": 1, "habits": 1},
        created_at=NOW,
        updated_at=NOW,
    )
    text = render_profile(profile, today=TODAY)
    assert "อายุ 27 ปี" in text
    assert "ธาตุเจ้าเรือน" in text
    assert "[a1] แพ้อาหารทะเล (กุ้ง)" in text
    assert "[h1] นอนดึกตี 1-2" in text
    assert "2026-07-06" in text  # noted_at provenance
    assert "ข้อมูลที่ยังขาด" not in text  # nothing missing on a full profile


def test_partial_profile_lists_only_missing_fields():
    profile = HealthProfile(user_id="U1", sex="หญิง", created_at=NOW, updated_at=NOW)
    text = render_profile(profile, today=TODAY)
    assert "ข้อมูลที่ยังขาด" in text
    assert "วันเกิด" in text.split("ข้อมูลที่ยังขาด")[-1]
    assert "เพศ" not in text.split("ข้อมูลที่ยังขาด")[-1]
