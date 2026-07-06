# Health Profile (ADR 0003) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Health Profile — a per-user current-state face sheet maintained as a deterministic projection of Health Record entries — per `docs/adr/0003-health-profile-projection.md`.

**Architecture:** New domain models (`ProfileItem`, `HealthProfile`, `ProfilePatch`) + a pure patch-application core wrapped by a Mongo repository (`health_profiles` + `profile_patches` collections). A Profile Updater LLM step (same structured-output pattern as `relevance_gate.py`) consumes *(rendered current profile + one HealthRecordEntry)* and emits item-level patch ops; it runs only when the Relevance Gate passes at Consultation close, and a rebuild function replays all entries through the same path. The rendered face sheet (with item IDs and missing-field hints) is injected into every Advisor turn. Everything is behind `health_profile_enabled` (the thesis ablation arm).

**Tech Stack:** Python 3.11, Pydantic v2 (frozen models), Motor/MongoDB, LangChain structured output, pytest + pytest-asyncio (auto mode) + mongomock-motor (new dev dep), uv.

**Sources:** `docs/adr/0003-health-profile-projection.md`, `CONTEXT.md` (Health Profile, Profile Updater, Ongoing Complaint), ADR 0002.

## Global Constraints

- **No agent tools for the profile, read or write.** The updater is code-triggered at Consultation close, gate-pass only; the Advisor sees the profile solely via prompt injection. (ADR 0003)
- **Projection invariant:** the updater's input is always *(current profile + one Health Record entry)* — never the raw transcript. Close-time update and rebuild use the same function.
- **Patch ops reference stable item IDs; unknown IDs fail loudly** — rejected ops are logged at WARNING and recorded in the patch-log document, never fuzzy-matched.
- **ธาตุเจ้าเรือน is code-derived from `birth_date`** via `MONTH_TO_ELEMENT`; it is never stored and never LLM-set.
- **⚠️ Domain data pending confirmation:** the `MONTH_TO_ELEMENT` values in Task 2 are a provisional published mapping. They MUST be confirmed against the TTM corpus before the thesis evaluation. The code contract (all 12 months covered, exactly the four elements ดิน/น้ำ/ลม/ไฟ) is fixed; the month assignments are replaceable data.
- **Immutability:** never mutate an existing model; `apply_ops` returns a new `HealthProfile`. All new models are `ConfigDict(frozen=True)` like the existing ones in `app/models/schemas.py`.
- **Mongo storage round-trip:** profile and patch documents are stored via `model_dump(mode="json")` (the schema contains `date` fields, which BSON cannot store) and parsed back through Pydantic. Strip/ignore `_id` on read.
- **Ablation flag:** `health_profile_enabled: bool = True` in `Settings`. Off ⇒ skip the updater at close AND skip injection — no other behavior change.
- **Provenance:** an item's `noted_at` is the `consultation_date` of the entry that added/last-updated it; the patch log carries `source_consultation_date`. (Entries have no separate ID field — `consultation_date` is the entry key, as in `HealthRecordRepository.get_by_date`.)
- Tests must not require a live MongoDB, a real LLM, or a populated `.env`: use `mongomock_motor.AsyncMongoMockClient`, monkeypatch `build_chat_model` at the *importing* module, and construct `Settings(line_channel_secret="test", line_channel_access_token="test", ...)` explicitly.
- Before every commit: `uv run pytest` fully green and `uv run ruff check app tests` clean. Ruff line length is 100.
- Commit messages: conventional commits, no attribution footer.

---

### Task 1: Profile domain models

**Files:**
- Create: `app/models/profile.py`
- Test: `tests/models/test_profile_models.py`

**Interfaces:**
- Consumes: nothing new (Pydantic only)
- Produces: `ProfileItem(id, text, noted_at)`, `HealthProfile(user_id, sex, birth_date, chronic_conditions, allergies, medications, habits, ongoing_complaints, notes, id_counters, created_at, updated_at)`, `ProfileOp(op, field, item_id, text)`, `ProfilePatch(ops)`, `AppliedPatch(user_id, source_consultation_date, applied_at, ops, rejected_ops)`, constant `LIST_FIELDS`

- [ ] **Step 1: Write the failing test**

Create `tests/models/test_profile_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/models/test_profile_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.profile'`

- [ ] **Step 3: Write the implementation**

Create `app/models/profile.py`:

```python
"""Health Profile domain models (see docs/adr/0003-health-profile-projection.md).

The profile is a per-user face sheet maintained as a deterministic
projection of Health Record entries. It is patched -- never rewritten --
by the Profile Updater at Consultation close, and injected whole into
every Advisor turn. The Advisor has no profile tools.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

LIST_FIELDS = (
    "chronic_conditions",
    "allergies",
    "medications",
    "habits",
    "ongoing_complaints",
)

ListField = Literal[
    "chronic_conditions", "allergies", "medications", "habits", "ongoing_complaints"
]


class ProfileItem(BaseModel):
    """One fact on the face sheet. noted_at is the consultation_date of the
    Health Record entry that added or last updated it (provenance)."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    noted_at: datetime


class HealthProfile(BaseModel):
    """The face sheet: current state only. Resolved items are removed (their
    history survives in the patch log and the Health Record). id_counters
    are monotonic per list field so removed item IDs are never reused."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    sex: str | None = None
    birth_date: date | None = None
    chronic_conditions: list[ProfileItem] = []
    allergies: list[ProfileItem] = []
    medications: list[ProfileItem] = []
    habits: list[ProfileItem] = []
    ongoing_complaints: list[ProfileItem] = []
    notes: str = ""
    id_counters: dict[str, int] = {}
    created_at: datetime
    updated_at: datetime


class ProfileOp(BaseModel):
    """One patch operation. Flat (no discriminated union) so weaker Advisor
    slots can emit it reliably as structured output. set_birth_date carries
    an ISO date in text; add/update/remove target a list field, with
    update/remove referencing an existing item_id."""

    model_config = ConfigDict(frozen=True)

    op: Literal["set_sex", "set_birth_date", "set_notes", "add", "update", "remove"]
    field: ListField | None = None
    item_id: str = ""
    text: str = ""


class ProfilePatch(BaseModel):
    """The Profile Updater's structured output: zero or more ops."""

    model_config = ConfigDict(frozen=True)

    ops: list[ProfileOp] = []


class AppliedPatch(BaseModel):
    """Audit-log document: what was applied (and rejected) at one close."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    source_consultation_date: datetime
    applied_at: datetime
    ops: list[ProfileOp] = []
    rejected_ops: list[ProfileOp] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/models/test_profile_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check app tests
git add app/models/profile.py tests/models/test_profile_models.py
git commit -m "feat: add Health Profile domain models (ADR 0003)"
```

---

### Task 2: Element derivation (ธาตุเจ้าเรือน)

**Files:**
- Create: `app/memory/element.py`
- Test: `tests/memory/test_element.py`

**Interfaces:**
- Consumes: nothing
- Produces: `MONTH_TO_ELEMENT: dict[int, str]`, `derive_element(birth_date: date) -> str`, `age_years(birth_date: date, today: date) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/memory/test_element.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/memory/test_element.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.memory.element'`

- [ ] **Step 3: Write the implementation**

Create `app/memory/element.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/memory/test_element.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check app tests
git add app/memory/element.py tests/memory/test_element.py
git commit -m "feat: derive dominant element from birth date (provisional corpus table)"
```

---

### Task 3: Patch application core + profile repository

**Files:**
- Create: `app/memory/health_profile.py`
- Modify: `pyproject.toml` (dev dep: mongomock-motor — via `uv add --group dev mongomock-motor`)
- Test: `tests/memory/test_health_profile.py`

**Interfaces:**
- Consumes: Task 1 models
- Produces:
  - `empty_profile(user_id: str, now: datetime) -> HealthProfile`
  - `apply_ops(profile: HealthProfile, ops: list[ProfileOp], *, noted_at: datetime, now: datetime) -> tuple[HealthProfile, list[ProfileOp], list[ProfileOp]]` (pure: new profile, applied, rejected)
  - `HealthProfileRepository(db)` with `async get(user_id) -> HealthProfile | None`, `async apply_patch(user_id, patch: ProfilePatch, *, source_consultation_date: datetime, now: datetime) -> HealthProfile`, `async delete_for_user(user_id) -> None`

- [ ] **Step 1: Add the mongomock dev dependency**

Run: `uv add --group dev mongomock-motor`
Expected: `pyproject.toml` dev group gains `mongomock-motor`, lockfile updated.

- [ ] **Step 2: Write the failing test**

Create `tests/memory/test_health_profile.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/memory/test_health_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.memory.health_profile'`

- [ ] **Step 4: Write the implementation**

Create `app/memory/health_profile.py`:

```python
"""Health Profile persistence and pure patch application (ADR 0003).

Writes happen only through apply_patch -- called by the Profile Updater
at Consultation close (gate-pass only) and by rebuild replay. Never
through an Advisor tool call. Rejected ops (unknown IDs, invalid dates)
are logged loudly and recorded in the patch log, never fuzzy-matched.
"""

import logging
from datetime import date, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.profile import (
    AppliedPatch,
    HealthProfile,
    ProfileOp,
    ProfilePatch,
)

logger = logging.getLogger(__name__)

PROFILE_COLLECTION = "health_profiles"
PATCH_COLLECTION = "profile_patches"

_ID_PREFIXES = {
    "chronic_conditions": "c",
    "allergies": "a",
    "medications": "m",
    "habits": "h",
    "ongoing_complaints": "o",
}


def empty_profile(user_id: str, now: datetime) -> HealthProfile:
    return HealthProfile(user_id=user_id, created_at=now, updated_at=now)


def apply_ops(
    profile: HealthProfile,
    ops: list[ProfileOp],
    *,
    noted_at: datetime,
    now: datetime,
) -> tuple[HealthProfile, list[ProfileOp], list[ProfileOp]]:
    """Pure: returns (new profile, applied ops, rejected ops). Never mutates."""
    data = profile.model_dump()
    applied: list[ProfileOp] = []
    rejected: list[ProfileOp] = []

    for op in ops:
        if op.op == "set_sex" and op.text:
            data["sex"] = op.text
        elif op.op == "set_notes":
            data["notes"] = op.text
        elif op.op == "set_birth_date":
            try:
                data["birth_date"] = date.fromisoformat(op.text)
            except ValueError:
                rejected.append(op)
                continue
        elif op.op == "add" and op.field in _ID_PREFIXES and op.text:
            counter = data["id_counters"].get(op.field, 0) + 1
            data["id_counters"][op.field] = counter
            data[op.field].append(
                {
                    "id": f"{_ID_PREFIXES[op.field]}{counter}",
                    "text": op.text,
                    "noted_at": noted_at,
                }
            )
        elif op.op == "update" and op.field in _ID_PREFIXES and op.text:
            match = next(
                (item for item in data[op.field] if item["id"] == op.item_id), None
            )
            if match is None:
                rejected.append(op)
                continue
            match["text"] = op.text
            match["noted_at"] = noted_at
        elif op.op == "remove" and op.field in _ID_PREFIXES:
            items = data[op.field]
            if not any(item["id"] == op.item_id for item in items):
                rejected.append(op)
                continue
            data[op.field] = [item for item in items if item["id"] != op.item_id]
        else:
            rejected.append(op)
            continue
        applied.append(op)

    data["updated_at"] = now
    return HealthProfile(**data), applied, rejected


class HealthProfileRepository:
    """One face-sheet document per user, plus an append-only patch log."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._profiles = db[PROFILE_COLLECTION]
        self._patches = db[PATCH_COLLECTION]

    async def get(self, user_id: str) -> HealthProfile | None:
        doc = await self._profiles.find_one({"user_id": user_id})
        if doc is None:
            return None
        return HealthProfile(**{k: v for k, v in doc.items() if k != "_id"})

    async def apply_patch(
        self,
        user_id: str,
        patch: ProfilePatch,
        *,
        source_consultation_date: datetime,
        now: datetime,
    ) -> HealthProfile:
        current = await self.get(user_id) or empty_profile(user_id, now)
        new_profile, applied, rejected = apply_ops(
            current, patch.ops, noted_at=source_consultation_date, now=now
        )
        if rejected:
            logger.warning(
                "Rejected %d profile op(s) for user %s: %s",
                len(rejected),
                user_id,
                [op.model_dump() for op in rejected],
            )
        await self._profiles.replace_one(
            {"user_id": user_id}, new_profile.model_dump(mode="json"), upsert=True
        )
        log_entry = AppliedPatch(
            user_id=user_id,
            source_consultation_date=source_consultation_date,
            applied_at=now,
            ops=applied,
            rejected_ops=rejected,
        )
        await self._patches.insert_one(log_entry.model_dump(mode="json"))
        return new_profile

    async def delete_for_user(self, user_id: str) -> None:
        """Rebuild support: clear the projection so replay starts clean."""
        await self._profiles.delete_one({"user_id": user_id})
        await self._patches.delete_many({"user_id": user_id})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/memory/test_health_profile.py -v`
Expected: 7 passed

- [ ] **Step 6: Lint, full suite, commit**

```bash
uv run ruff check app tests && uv run pytest
git add app/memory/health_profile.py tests/memory/test_health_profile.py pyproject.toml uv.lock
git commit -m "feat: add Health Profile repository with pure patch application"
```

---

### Task 4: Face-sheet renderer

**Files:**
- Create: `app/memory/profile_render.py`
- Test: `tests/memory/test_profile_render.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `derive_element`/`age_years`
- Produces: `render_profile(profile: HealthProfile, *, today: date) -> str` — the single rendered view consumed by BOTH the updater prompt (needs the `[id]` labels) and the Advisor injection (needs the missing-field hints for intake)

- [ ] **Step 1: Write the failing test**

Create `tests/memory/test_profile_render.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/memory/test_profile_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.memory.profile_render'`

- [ ] **Step 3: Write the implementation**

Create `app/memory/profile_render.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/memory/test_profile_render.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check app tests
git add app/memory/profile_render.py tests/memory/test_profile_render.py
git commit -m "feat: render Health Profile face sheet for prompt injection"
```

---

### Task 5: Profile Updater + rebuild by replay

**Files:**
- Create: `app/memory/profile_updater.py`
- Modify: `app/memory/health_record.py` (add `all_for_user`)
- Modify: `app/models/schemas.py` (tz-aware validator — Mongo reads return naive datetimes; naive means UTC in this system)
- Test: `tests/memory/test_profile_updater.py`, `tests/models/test_schemas.py`

**Interfaces:**
- Consumes: Tasks 1/3/4; `build_chat_model` from `app/advisor/llm.py` (same structured-output pattern as `app/memory/relevance_gate.py:60-64`); `HealthRecordEntry`
- Produces:
  - `update_profile_from_entry(profile_repo, *, user_id: str, entry: HealthRecordEntry, settings: Settings, now: datetime | None = None) -> HealthProfile`
  - `rebuild_profile(profile_repo, record_repo, *, user_id: str, settings: Settings) -> HealthProfile | None`
  - `HealthRecordRepository.all_for_user(user_id: str) -> list[HealthRecordEntry]` (chronological ascending)

- [ ] **Step 1: Write the failing test**

Create `tests/memory/test_profile_updater.py`:

```python
from datetime import UTC, datetime

from mongomock_motor import AsyncMongoMockClient

import app.memory.profile_updater as updater_module
from app.memory.health_profile import HealthProfileRepository
from app.memory.health_record import HealthRecordRepository
from app.memory.profile_updater import rebuild_profile, update_profile_from_entry
from app.models.profile import ProfileOp, ProfilePatch
from app.models.schemas import HealthRecordEntry

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _entry(day: int, complaint: str) -> HealthRecordEntry:
    return HealthRecordEntry(
        user_id="U1",
        consultation_date=datetime(2026, 7, day, 9, 0, tzinfo=UTC),
        chief_complaint=complaint,
        symptoms=[complaint],
        advice_given="ดื่มน้ำอุ่น พักผ่อน",
        conversation_summary=f"ผู้ใช้ปรึกษาเรื่อง{complaint}",
    )


PATCHES_BY_COMPLAINT = {
    "นอนไม่หลับ": ProfilePatch(
        ops=[ProfileOp(op="add", field="ongoing_complaints", text="นอนไม่หลับ ~2 สัปดาห์")]
    ),
    "ปวดหัว": ProfilePatch(
        ops=[
            ProfileOp(op="add", field="habits", text="นอนดึกตี 1-2"),
            ProfileOp(op="set_sex", text="ชาย"),
        ]
    ),
}


class _FakeStructuredModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        assert schema is ProfilePatch
        return self

    async def ainvoke(self, prompt: str) -> ProfilePatch:
        self.prompts.append(prompt)
        # Match on the entry-section marker only: the rendered profile
        # legitimately echoes prior complaint text (the projection carries
        # it forward), so a bare-substring match would re-match old entries.
        for complaint, patch in PATCHES_BY_COMPLAINT.items():
            if f"Chief complaint: {complaint}" in prompt:
                return patch
        return ProfilePatch()


def _settings():
    from app.config import Settings

    return Settings(line_channel_secret="test", line_channel_access_token="test")


async def test_update_builds_prompt_from_profile_and_entry_only(monkeypatch):
    fake = _FakeStructuredModel()
    monkeypatch.setattr(updater_module, "build_chat_model", lambda slot: fake)
    repo = HealthProfileRepository(AsyncMongoMockClient()["test_db"])

    entry = _entry(1, "นอนไม่หลับ")
    profile = await update_profile_from_entry(
        repo, user_id="U1", entry=entry, settings=_settings(), now=NOW
    )

    assert [i.text for i in profile.ongoing_complaints] == ["นอนไม่หลับ ~2 สัปดาห์"]
    assert profile.ongoing_complaints[0].noted_at == entry.consultation_date
    prompt = fake.prompts[0]
    assert "ยังไม่มีข้อมูล" in prompt  # rendered (empty) profile is in the prompt
    assert "นอนไม่หลับ" in prompt  # the entry is in the prompt
    assert "user:" not in prompt and "advisor:" not in prompt  # never a transcript


async def test_rebuild_replays_entries_and_matches_incremental(monkeypatch):
    fake = _FakeStructuredModel()
    monkeypatch.setattr(updater_module, "build_chat_model", lambda slot: fake)
    db = AsyncMongoMockClient()["test_db"]
    profile_repo = HealthProfileRepository(db)
    record_repo = HealthRecordRepository(db)

    entries = [_entry(1, "นอนไม่หลับ"), _entry(3, "ปวดหัว")]
    for entry in entries:
        await record_repo.insert(entry)

    incremental = None
    for entry in entries:
        incremental = await update_profile_from_entry(
            profile_repo, user_id="U1", entry=entry, settings=_settings(), now=NOW
        )

    rebuilt = await rebuild_profile(
        profile_repo, record_repo, user_id="U1", settings=_settings()
    )

    assert rebuilt is not None and incremental is not None
    exclude = {"created_at", "updated_at"}
    assert rebuilt.model_dump(exclude=exclude) == incremental.model_dump(exclude=exclude)
    assert rebuilt.sex == "ชาย"
    assert [i.id for i in rebuilt.ongoing_complaints] == ["o1"]
    assert [i.id for i in rebuilt.habits] == ["h1"]


async def test_rebuild_with_no_entries_returns_none(monkeypatch):
    fake = _FakeStructuredModel()
    monkeypatch.setattr(updater_module, "build_chat_model", lambda slot: fake)
    db = AsyncMongoMockClient()["test_db"]
    result = await rebuild_profile(
        HealthProfileRepository(db),
        HealthRecordRepository(db),
        user_id="U-nobody",
        settings=_settings(),
    )
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/memory/test_profile_updater.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.memory.profile_updater'`

- [ ] **Step 3: Add `all_for_user` to the record repository**

In `app/memory/health_record.py`, after the `get_by_date` method, add:

```python
    async def all_for_user(self, user_id: str) -> list[HealthRecordEntry]:
        """All entries chronologically -- the replay source for rebuilding
        the Health Profile projection (ADR 0003)."""
        cursor = self._collection.find({"user_id": user_id}).sort("consultation_date", 1)
        return [HealthRecordEntry(**doc) async for doc in cursor]
```

- [ ] **Step 3b: Normalize Mongo-read datetimes at the model boundary**

The Motor client is not `tz_aware`, so datetimes read back from MongoDB are naive even though this system only ever stores UTC. Without this, entries fetched by `all_for_user` carry naive `consultation_date`s and the rebuild-equivalence test fails on tzinfo alone. Validate at the boundary:

In `app/models/schemas.py`, change the imports to:

```python
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator
```

and add to `HealthRecordEntry` (after the field declarations):

```python
    @field_validator("consultation_date")
    @classmethod
    def _assume_utc_when_naive(cls, value: datetime) -> datetime:
        """MongoDB returns naive datetimes (the client is not tz_aware);
        this system only ever stores UTC, so naive means UTC."""
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
```

Create `tests/models/test_schemas.py`:

```python
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
```

- [ ] **Step 4: Write the updater implementation**

Create `app/memory/profile_updater.py`:

```python
"""Profile Updater: fold one Health Record entry into the Health Profile.

The projection invariant (ADR 0003): input is always (current profile +
one entry) -- never the raw transcript -- so close-time updates and
rebuild-by-replay are the same code path, and the profile is rebuildable
from the record at any time. LLM-scored but code-triggered, like the
Relevance Gate. The Advisor cannot invoke this.
"""

from datetime import UTC, datetime

from app.advisor.llm import build_chat_model
from app.config import Settings
from app.memory.health_profile import HealthProfileRepository, empty_profile
from app.memory.health_record import HealthRecordRepository
from app.memory.profile_render import render_profile
from app.models.profile import HealthProfile, ProfilePatch
from app.models.schemas import HealthRecordEntry

UPDATE_PROMPT = """\
You maintain the Health Profile of a user of a Thai Traditional Medicine \
self-care advisor. The profile is a face sheet of their CURRENT state \
(sex, birth date, chronic conditions, allergies, regular medicines/herbs, \
habits, ongoing complaints).

Current profile — list items are labeled with stable IDs in brackets:
{profile}

A consultation just closed. Its Health Record entry:
{entry}

Emit patch operations that bring the profile up to date. Rules:
- Only state facts explicitly present in the entry. Never invent.
- To change or resolve an existing fact, use update/remove with the exact \
ID shown in brackets. Never invent IDs.
- Use add only for facts not already on the profile.
- set_birth_date only if the entry states a birth date; text must be an \
ISO date (YYYY-MM-DD).
- An ongoing complaint the user reports as resolved should be removed.
- If the entry adds nothing profile-worthy, return an empty ops list.
"""


def _render_entry(entry: HealthRecordEntry) -> str:
    lines = [
        f"Consultation date: {entry.consultation_date.date().isoformat()}",
        f"Chief complaint: {entry.chief_complaint}",
    ]
    if entry.symptoms:
        lines.append("Symptoms: " + ", ".join(entry.symptoms))
    lines.append(f"Advice given: {entry.advice_given}")
    lines.append(f"Summary: {entry.conversation_summary}")
    return "\n".join(lines)


async def update_profile_from_entry(
    profile_repo: HealthProfileRepository,
    *,
    user_id: str,
    entry: HealthRecordEntry,
    settings: Settings,
    now: datetime | None = None,
) -> HealthProfile:
    now = now or datetime.now(UTC)
    current = await profile_repo.get(user_id) or empty_profile(user_id, now)

    prompt = UPDATE_PROMPT.format(
        profile=render_profile(current, today=now.date()),
        entry=_render_entry(entry),
    )
    model = build_chat_model(settings.advisor_slot())
    patch: ProfilePatch = await model.with_structured_output(ProfilePatch).ainvoke(prompt)

    return await profile_repo.apply_patch(
        user_id, patch, source_consultation_date=entry.consultation_date, now=now
    )


async def rebuild_profile(
    profile_repo: HealthProfileRepository,
    record_repo: HealthRecordRepository,
    *,
    user_id: str,
    settings: Settings,
) -> HealthProfile | None:
    """Rebuild the projection by replaying all entries chronologically."""
    entries = await record_repo.all_for_user(user_id)
    if not entries:
        return None
    await profile_repo.delete_for_user(user_id)
    profile: HealthProfile | None = None
    for entry in entries:
        profile = await update_profile_from_entry(
            profile_repo, user_id=user_id, entry=entry, settings=settings
        )
    return profile
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/memory/test_profile_updater.py -v`
Expected: 3 passed

- [ ] **Step 6: Lint, full suite, commit**

```bash
uv run ruff check app tests && uv run pytest
git add app/memory/profile_updater.py app/memory/health_record.py app/models/schemas.py tests/memory/test_profile_updater.py tests/models/test_schemas.py
git commit -m "feat: add Profile Updater with rebuild-by-replay (projection of entries)"
```

---

### Task 6: Wire into config, Advisor, and dispatcher

**Files:**
- Modify: `app/config.py` (flag), `app/advisor/graph.py` (injection), `app/advisor/prompts.py` (intake instruction), `app/pipeline/dispatcher.py` (close-path + injection)
- Test: `tests/advisor/test_context_block.py`, `tests/pipeline/test_dispatcher_profile.py`

**Interfaces:**
- Consumes: Tasks 3/4/5
- Produces: `Settings.health_profile_enabled: bool = True`; `run_advisor(..., health_profile_block: str = "")`; dispatcher behavior: updater runs iff gate passes AND flag on; rendered profile injected iff flag on

- [ ] **Step 1: Write the failing tests**

Create `tests/advisor/test_context_block.py`:

```python
from app.advisor.graph import _build_context_block
from app.advisor.prompts import SYSTEM_PROMPT


def test_context_block_puts_profile_before_records_and_rag():
    block = _build_context_block(
        retrieved_passages=["TTM passage"],
        recent_records_summary="record summary",
        health_profile_block="อายุ 27 ปี เพศชาย",
    )
    profile_pos = block.index("อายุ 27 ปี")
    records_pos = block.index("record summary")
    rag_pos = block.index("TTM passage")
    assert profile_pos < records_pos < rag_pos


def test_context_block_omits_profile_section_when_empty():
    block = _build_context_block(
        retrieved_passages=[], recent_records_summary="", health_profile_block=""
    )
    assert block == ""


def test_system_prompt_covers_profile_and_single_intake_question():
    assert "Health Profile" in SYSTEM_PROMPT
    assert "ONE" in SYSTEM_PROMPT
```

Create `tests/pipeline/test_dispatcher_profile.py`:

```python
from datetime import UTC, datetime

from mongomock_motor import AsyncMongoMockClient

import app.pipeline.dispatcher as dispatcher
from app.config import Settings
from app.memory.working_buffer import WorkingBufferRepository
from app.models.schemas import (
    ConsultationTurn,
    HealthRecordEntry,
    RelevanceGateResult,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

ENTRY = HealthRecordEntry(
    user_id="U1",
    consultation_date=NOW,
    chief_complaint="นอนไม่หลับ",
    symptoms=["นอนไม่หลับ"],
    advice_given="ดื่มน้ำอุ่น",
    conversation_summary="ผู้ใช้ปรึกษาเรื่องนอนไม่หลับ",
)

STALE_TURNS = [ConsultationTurn(role="user", text="นอนไม่หลับ", timestamp=NOW)]


def _settings(**overrides) -> Settings:
    return Settings(
        line_channel_secret="test", line_channel_access_token="test", **overrides
    )


class _Recorder:
    def __init__(self) -> None:
        self.updater_calls: list[str] = []
        self.profile_blocks: list[str] = []


def _patch_dispatcher(monkeypatch, recorder: _Recorder, *, stale: bool) -> None:
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(dispatcher, "get_database", lambda settings: db)

    async def fake_pop_if_stale(self, user_id, gap_hours):
        return STALE_TURNS if stale else []

    async def fake_append_turn(self, user_id, turn):
        return None

    monkeypatch.setattr(WorkingBufferRepository, "pop_if_stale", fake_pop_if_stale)
    monkeypatch.setattr(WorkingBufferRepository, "append_turn", fake_append_turn)

    async def fake_summarize(turns, *, user_id, settings):
        return RelevanceGateResult(has_health_content=True, entry=ENTRY)

    monkeypatch.setattr(dispatcher, "summarize_consultation", fake_summarize)

    async def fake_update(profile_repo, *, user_id, entry, settings, now=None):
        recorder.updater_calls.append(user_id)
        from app.memory.health_profile import empty_profile

        return empty_profile(user_id, NOW)

    monkeypatch.setattr(dispatcher, "update_profile_from_entry", fake_update)

    async def fake_retrieve(text):
        return []

    monkeypatch.setattr(dispatcher, "retrieve_passages", fake_retrieve)
    monkeypatch.setattr(dispatcher, "build_advisor_agent", lambda settings, tools: None)

    async def fake_run_advisor(agent, *, user_message, retrieved_passages,
                               recent_records_summary, health_profile_block=""):
        recorder.profile_blocks.append(health_profile_block)
        return "คำตอบ"

    monkeypatch.setattr(dispatcher, "run_advisor", fake_run_advisor)


async def test_gate_pass_triggers_updater_and_injects_profile(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, stale=True)

    reply = await dispatcher._run_consultation_turn("U1", "สวัสดี", _settings())

    assert reply == "คำตอบ"
    assert recorder.updater_calls == ["U1"]
    assert recorder.profile_blocks[0] != ""  # rendered profile injected


async def test_flag_off_skips_updater_and_injection(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, stale=True)

    await dispatcher._run_consultation_turn(
        "U1", "สวัสดี", _settings(health_profile_enabled=False)
    )

    assert recorder.updater_calls == []
    assert recorder.profile_blocks == [""]


async def test_no_stale_buffer_means_no_update_but_still_injects(monkeypatch):
    recorder = _Recorder()
    _patch_dispatcher(monkeypatch, recorder, stale=False)

    await dispatcher._run_consultation_turn("U1", "สวัสดี", _settings())

    assert recorder.updater_calls == []
    assert recorder.profile_blocks[0] != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/advisor/test_context_block.py tests/pipeline/test_dispatcher_profile.py -v`
Expected: FAIL — `_build_context_block()` doesn't accept `health_profile_block`, `SYSTEM_PROMPT` lacks profile text, dispatcher has no `update_profile_from_entry` attribute.

- [ ] **Step 3: Implement the wiring**

In `app/config.py`, after the `health_record_inject_count: int = 3` line, add:

```python
    # Health Profile (ADR 0003) -- the memory ablation arm: off skips both
    # the Profile Updater at close and the face-sheet injection.
    health_profile_enabled: bool = True
```

In `app/advisor/graph.py`, replace `_build_context_block` and `run_advisor` with:

```python
def _build_context_block(
    retrieved_passages: list[str],
    recent_records_summary: str,
    health_profile_block: str,
) -> str:
    sections = []
    if health_profile_block:
        sections.append(f"Health Profile (current face sheet):\n{health_profile_block}")
    if recent_records_summary:
        sections.append(f"Recent Health Record entries for this user:\n{recent_records_summary}")
    if retrieved_passages:
        joined = "\n\n".join(retrieved_passages)
        sections.append(f"Relevant TTM reference material:\n{joined}")
    return "\n\n".join(sections)


async def run_advisor(
    agent: CompiledStateGraph,
    *,
    user_message: str,
    retrieved_passages: list[str],
    recent_records_summary: str,
    health_profile_block: str = "",
) -> str:
    """Run one Advisor turn and return its final Thai-language reply text."""
    context_block = _build_context_block(
        retrieved_passages, recent_records_summary, health_profile_block
    )
    text = (
        f"{context_block}\n\n---\n\nUser message: {user_message}"
        if context_block
        else user_message
    )

    result = await agent.ainvoke({"messages": [HumanMessage(content=text)]})
    final_message = result["messages"][-1]
    return final_message.content
```

In `app/advisor/prompts.py`, replace the `## Memory` section (the final paragraph of `SYSTEM_PROMPT`) with:

```python
## Memory
You may be given this user's Health Profile (a face sheet of their \
current state: element, chronic conditions, allergies, habits, ongoing \
complaints) and a summary of their recent Health Record entries. Use \
them for continuity and safety (never advise against a listed allergy \
or condition), but do not fabricate history that wasn't given to you. \
You have read-only tools to look up older entries when the recent \
summary isn't enough. You cannot edit the profile; it is updated \
automatically after consultations.

If the Health Profile lists missing information (ข้อมูลที่ยังขาด), you \
may weave in at most ONE natural intake question per conversation when \
it fits the context -- for example, asking birth date before giving an \
element-based assessment. Never interrogate or ask a list of questions.
"""
```

In `app/pipeline/dispatcher.py`:

Add imports:

```python
from app.memory.health_profile import HealthProfileRepository, empty_profile
from app.memory.profile_render import render_profile
from app.memory.profile_updater import update_profile_from_entry
```

In `_run_consultation_turn`, after `record_repo = HealthRecordRepository(db)` add:

```python
    profile_repo = HealthProfileRepository(db)
```

Replace the stale-close block:

```python
    stale_turns = await buffer_repo.pop_if_stale(user_id, settings.consultation_gap_hours)
    if stale_turns:
        gate_result = await summarize_consultation(stale_turns, user_id=user_id, settings=settings)
        if gate_result.has_health_content and gate_result.entry is not None:
            await record_repo.insert(gate_result.entry)
            if settings.health_profile_enabled:
                # The only Health Profile write path: gate-passed close (ADR 0003).
                await update_profile_from_entry(
                    profile_repo, user_id=user_id, entry=gate_result.entry, settings=settings
                )
```

Replace the context-retrieval block (before `tools = ...`):

```python
    health_profile_block = ""
    if settings.health_profile_enabled:
        now = datetime.now(UTC)
        profile = await profile_repo.get(user_id) or empty_profile(user_id, now)
        health_profile_block = render_profile(profile, today=now.date())

    recent_entries = await record_repo.recent(user_id, settings.health_record_inject_count)
    recent_summary = "\n".join(entry.conversation_summary for entry in recent_entries)
    passages = await retrieve_passages(incoming_text)
```

And pass the block to the advisor:

```python
    reply_text = await run_advisor(
        agent,
        user_message=incoming_text,
        retrieved_passages=passages,
        recent_records_summary=recent_summary,
        health_profile_block=health_profile_block,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/advisor/test_context_block.py tests/pipeline/test_dispatcher_profile.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint, full suite, commit**

```bash
uv run ruff check app tests && uv run pytest
git add app/config.py app/advisor/graph.py app/advisor/prompts.py app/pipeline/dispatcher.py tests/advisor/test_context_block.py tests/pipeline/test_dispatcher_profile.py
git commit -m "feat: wire Health Profile into close path and Advisor injection"
```

---

### Task 7: Documentation sync (drop "pending build")

**Files:**
- Modify: `docs/message-flow.md`, `docs/message-flow.html`, `docs/superpowers/specs/2026-07-06-message-flow-visualization-design.md`

The Health Profile flow is now built; the visualization docs must stop labeling it pending. No behavior claims change — only the pending markers.

- [ ] **Step 1: Update `docs/message-flow.md`**

- In the intro paragraph, replace the sentence `Dashed elements are approved design, pending build ([ADR 0003](adr/0003-health-profile-projection.md)).` with `The Health Profile write path is defined by [ADR 0003](adr/0003-health-profile-projection.md).`
- In the Mermaid block: change the `PU` label line `patch Health Profile<br/>(ADR 0003 — pending)` to `patch Health Profile<br/>(ADR 0003)`; remove the line `classDef planned stroke-dasharray: 6 4` and the line `class PU planned`; change the `CTX` label `Health Profile* + recent Health Record summaries + RAG passages` to `Health Profile + recent Health Record summaries + RAG passages`.
- Delete the asterisk footnote paragraph beginning `\* Health Profile injection into context is approved design`.
- In the close-branch prose, replace `([ADR 0003](adr/0003-health-profile-projection.md) — pending build).` with `([ADR 0003](adr/0003-health-profile-projection.md)).`

- [ ] **Step 2: Re-run the Mermaid render-check**

```bash
TMP=$(mktemp -d)
python3 - "$TMP" <<'EOF'
import re, sys, pathlib
md = pathlib.Path("docs/message-flow.md").read_text()
m = re.search(r"```mermaid\n(.*?)```", md, re.S)
assert m, "no mermaid block found"
pathlib.Path(sys.argv[1], "flow.mmd").write_text(m.group(1))
print("extracted OK")
EOF
npx -y @mermaid-js/mermaid-cli -i "$TMP/flow.mmd" -o "$TMP/flow.svg"
test -s "$TMP/flow.svg" && echo RENDER_OK
```

Expected: `RENDER_OK`

- [ ] **Step 3: Update `docs/message-flow.html`**

- Change the `PU` node label text `(ADR 0003 — pending)` to `(ADR 0003)` and remove its `stroke-dasharray="6 4"` attribute.
- Remove the legend's dashed "pending build" swatch row.
- In the `SCENARIOS` data, replace every occurrence of `(ADR 0003 — pending build)` with `(ADR 0003)` (occurs in the feelings, gap, and firstvisit notes).
- Re-run the brief's self-checks:

```bash
grep -nE '(src|href)="https?://|@import|url\(https?:|fetch\(|XMLHttpRequest' docs/message-flow.html && echo FAIL || echo NO_EXTERNAL_REFS
grep -c "pending" docs/message-flow.html
```

Expected: `NO_EXTERNAL_REFS`, then `0` (no "pending" remains).

- [ ] **Step 4: Update the spec's verification caveat**

In `docs/superpowers/specs/2026-07-06-message-flow-visualization-design.md`, replace the bullet beginning `- Health Profile edges checked against` (through `remove this caveat`) with:

```markdown
- Health Profile edges verified against the implementation
  (`app/memory/profile_updater.py`, `app/memory/health_profile.py`,
  `app/pipeline/dispatcher.py`) as of the Health Profile build.
```

And in the Purpose section, change `(approved, implementation pending)` to `(implemented)`.

- [ ] **Step 5: Commit**

```bash
git add docs/message-flow.md docs/message-flow.html docs/superpowers/specs/2026-07-06-message-flow-visualization-design.md
git commit -m "docs: mark Health Profile flow as built in message-flow docs"
```

Note for the controller (not this task's agent): republish the HTML artifact from the main session after this commit so the hosted version matches.

---

## Post-plan follow-ups (not tasks)

- **Confirm `MONTH_TO_ELEMENT` against the TTM corpus** (Global Constraints ⚠️). The table ships provisional; the thesis evaluation must not run on unconfirmed domain data.
- Backfill existing users when desired: `rebuild_profile` is callable from a REPL or a future management command; no CLI is included (YAGNI — there are no production users yet).
- The uncommitted design docs from the grilling session (`CONTEXT.md`, ADR 0003, spec revision, this plan) should be committed before or with Task 1.
