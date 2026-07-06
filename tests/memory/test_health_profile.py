from datetime import UTC, date, datetime

from mongomock_motor import AsyncMongoMockClient

from app.memory.health_profile import HealthProfileRepository, apply_ops, empty_profile
from app.models.profile import ProfileOp, ProfilePatch

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
CONSULT = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def _profile():
    return empty_profile("U1", NOW)


def test_add_assigns_field_prefixed_sequential_ids():
    ops = [
        ProfileOp(op="add", field="allergies", text="แพ้กุ้ง"),
        ProfileOp(op="add", field="allergies", text="แพ้ยาแอสไพริน"),
        ProfileOp(op="add", field="habits", text="สูบบุหรี่วันละครึ่งซอง"),
    ]
    new, applied, rejected = apply_ops(_profile(), ops, noted_at=CONSULT, now=NOW)
    assert [i.id for i in new.allergies] == ["a1", "a2"]
    assert [i.id for i in new.habits] == ["h1"]
    assert new.allergies[0].noted_at == CONSULT
    assert len(applied) == 3 and rejected == []


def test_removed_item_ids_are_never_reused():
    step1, _, _ = apply_ops(
        _profile(), [ProfileOp(op="add", field="allergies", text="แพ้กุ้ง")],
        noted_at=CONSULT, now=NOW,
    )
    step2, _, _ = apply_ops(
        step1, [ProfileOp(op="remove", field="allergies", item_id="a1")],
        noted_at=CONSULT, now=NOW,
    )
    step3, _, _ = apply_ops(
        step2, [ProfileOp(op="add", field="allergies", text="แพ้อาหารทะเล")],
        noted_at=CONSULT, now=NOW,
    )
    assert [i.id for i in step3.allergies] == ["a2"]


def test_update_changes_text_and_refreshes_noted_at():
    later = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)
    step1, _, _ = apply_ops(
        _profile(), [ProfileOp(op="add", field="habits", text="สูบบุหรี่วันละครึ่งซอง")],
        noted_at=CONSULT, now=NOW,
    )
    step2, applied, rejected = apply_ops(
        step1, [ProfileOp(op="update", field="habits", item_id="h1", text="ลดบุหรี่เหลือวันละ 2-3 มวน")],
        noted_at=later, now=NOW,
    )
    assert step2.habits[0].text == "ลดบุหรี่เหลือวันละ 2-3 มวน"
    assert step2.habits[0].noted_at == later
    assert len(applied) == 1 and rejected == []


def test_unknown_item_id_is_rejected_not_fuzzy_matched():
    step1, _, _ = apply_ops(
        _profile(), [ProfileOp(op="add", field="allergies", text="แพ้อาหารทะเล (กุ้ง)")],
        noted_at=CONSULT, now=NOW,
    )
    op = ProfileOp(op="remove", field="allergies", item_id="a99")
    step2, applied, rejected = apply_ops(step1, [op], noted_at=CONSULT, now=NOW)
    assert step2.allergies == step1.allergies
    assert applied == [] and rejected == [op]


def test_scalar_ops_and_invalid_birth_date_rejection():
    ops = [
        ProfileOp(op="set_sex", text="ชาย"),
        ProfileOp(op="set_birth_date", text="1998-11-02"),
        ProfileOp(op="set_birth_date", text="พ.ศ. 2541"),
    ]
    new, applied, rejected = apply_ops(_profile(), ops, noted_at=CONSULT, now=NOW)
    assert new.sex == "ชาย"
    assert new.birth_date == date(1998, 11, 2)
    assert len(applied) == 2 and len(rejected) == 1


def test_apply_ops_does_not_mutate_input_profile():
    original = _profile()
    apply_ops(original, [ProfileOp(op="add", field="habits", text="นอนดึก")],
              noted_at=CONSULT, now=NOW)
    assert original.habits == [] and original.id_counters == {}


async def test_repository_upserts_reads_back_and_logs_patches():
    db = AsyncMongoMockClient()["test_db"]
    repo = HealthProfileRepository(db)
    patch = ProfilePatch(ops=[
        ProfileOp(op="add", field="ongoing_complaints", text="นอนไม่หลับ ~2 สัปดาห์"),
        ProfileOp(op="remove", field="allergies", item_id="a99"),
    ])
    saved = await repo.apply_patch("U1", patch, source_consultation_date=CONSULT, now=NOW)
    assert [i.id for i in saved.ongoing_complaints] == ["o1"]

    read_back = await repo.get("U1")
    assert read_back == saved

    log = await db["profile_patches"].find({"user_id": "U1"}).to_list(None)
    assert len(log) == 1
    assert len(log[0]["ops"]) == 1 and len(log[0]["rejected_ops"]) == 1

    await repo.delete_for_user("U1")
    assert await repo.get("U1") is None
    assert await db["profile_patches"].find({"user_id": "U1"}).to_list(None) == []
