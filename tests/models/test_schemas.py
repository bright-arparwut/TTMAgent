from datetime import UTC, datetime

from app.models.schemas import ConsultationTurn, HealthRecordEntry


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
