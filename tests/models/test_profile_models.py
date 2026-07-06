from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.models.profile import (
    LIST_FIELDS,
    HealthProfile,
    ProfileItem,
    ProfileOp,
    ProfilePatch,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def test_empty_profile_has_no_facts_and_zero_counters():
    profile = HealthProfile(user_id="U1", created_at=NOW, updated_at=NOW)
    assert profile.sex is None
    assert profile.birth_date is None
    for field in LIST_FIELDS:
        assert getattr(profile, field) == []
    assert profile.id_counters == {}
    assert profile.notes == ""


def test_profile_models_are_frozen():
    item = ProfileItem(id="a1", text="แพ้กุ้ง", noted_at=NOW)
    with pytest.raises(ValidationError):
        item.text = "changed"


def test_profile_round_trips_through_json_mode_dump():
    profile = HealthProfile(
        user_id="U1",
        birth_date=date(1998, 11, 2),
        allergies=[ProfileItem(id="a1", text="แพ้กุ้ง", noted_at=NOW)],
        id_counters={"allergies": 1},
        created_at=NOW,
        updated_at=NOW,
    )
    restored = HealthProfile(**profile.model_dump(mode="json"))
    assert restored == profile


def test_profile_op_rejects_unknown_op_name():
    with pytest.raises(ValidationError):
        ProfileOp(op="delete_everything")


def test_profile_patch_defaults_to_no_ops():
    assert ProfilePatch().ops == []
