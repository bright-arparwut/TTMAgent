from datetime import UTC, datetime

from app.models.schemas import HealthRecordEntry


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
