from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.schemas import ConsultationTurn, HealthRecordEntry, TongueDescription


def _tongue_description(**overrides) -> TongueDescription:
    fields: dict = dict(
        color="แดงเข้ม",
        coating="ฝ้าขาวหนา",
        size="ปกติ",
        shape="ขอบลิ้นมีรอยหยักของฟัน",
        spots="ไม่มีจุด",
        quality="clear",
    )
    fields.update(overrides)
    return TongueDescription(**fields)


def test_tongue_description_holds_the_five_axes_as_thai_free_text():
    description = _tongue_description()

    assert description.color == "แดงเข้ม"
    assert description.coating == "ฝ้าขาวหนา"
    assert description.size == "ปกติ"
    assert description.shape == "ขอบลิ้นมีรอยหยักของฟัน"
    assert description.spots == "ไม่มีจุด"


def test_tongue_description_notes_defaults_to_empty_string():
    description = _tongue_description()

    assert description.notes == ""


def test_tongue_description_notes_can_hold_the_rare_visible_case():
    # e.g. sublingual veins or movement, glimpsed despite being excluded
    # from the schema's five axes (a still top-side crop cannot normally
    # witness them) -- notes is the escape hatch.
    description = _tongue_description(notes="เห็นหลอดเลือดใต้ลิ้นเล็กน้อยที่มุมภาพ")

    assert description.notes == "เห็นหลอดเลือดใต้ลิ้นเล็กน้อยที่มุมภาพ"


def test_tongue_description_quality_rejects_values_outside_the_literal():
    with pytest.raises(ValidationError):
        _tongue_description(quality="great")


def test_tongue_description_has_no_moisture_field():
    # Moisture folds into the axes via the prompt (e.g. "ชื้น"/"แห้ง" as
    # part of สี or ฝ้า) rather than a standalone field.
    assert "moisture" not in TongueDescription.model_fields


def test_tongue_description_has_no_boolean_or_legacy_fields():
    # No Literals, no booleans -- cracks/teeth marks are prompt-guided
    # coverage under `shape`, not their own fields.
    legacy_names = {
        "body_color",
        "body_shape",
        "coating_color",
        "coating_thickness",
        "moisture",
        "cracks",
        "teeth_marks",
    }
    assert legacy_names.isdisjoint(TongueDescription.model_fields)


def test_tongue_description_is_frozen():
    description = _tongue_description()

    with pytest.raises(ValidationError):
        description.color = "ซีด"  # type: ignore[misc]


def test_naive_consultation_date_is_assumed_utc():
    entry = HealthRecordEntry(
        user_id="U1",
        consultation_date=datetime(2026, 7, 1, 9, 0),
        chief_complaint="x",
        advice_given="y",
        conversation_summary="z",
    )
    assert entry.consultation_date == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    assert entry.consultation_date.tzinfo is not None


def test_naive_consultation_turn_timestamp_is_assumed_utc():
    turn = ConsultationTurn(role="user", text="สวัสดี", timestamp=datetime(2026, 7, 1, 9, 0))
    assert turn.timestamp == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    assert turn.timestamp.tzinfo is not None


def test_aware_consultation_turn_timestamp_is_left_untouched():
    aware = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    turn = ConsultationTurn(role="user", text="สวัสดี", timestamp=aware)
    assert turn.timestamp == aware
