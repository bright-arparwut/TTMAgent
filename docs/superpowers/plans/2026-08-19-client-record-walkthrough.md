# Client Record Walkthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained HTML page that follows one synthetic client across four consultations, showing the Health Record entries being written and the Health Profile (แฟ้ม) accumulating from them.

**Architecture:** A Python generator defines the four consultations and their `ProfileOp` lists, runs them through the *real* `apply_ops()` and `render_profile()`, and injects the resulting JSON into a hand-authored HTML page between marker comments. The page is a single file with no fetch and no external assets. A test asserts the committed page matches what regeneration produces, so it cannot silently drift when the renderer changes.

**Tech Stack:** Python 3.11+, pydantic models already in `app/models/`, pytest (asyncio_mode auto), vanilla HTML/CSS/JS. Run everything through `uv run`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-19-client-record-walkthrough-design.md`. Read it before starting.
- Language: Thai narrative and data, English structure (headings, pane labels, field names, op names).
- Ruff config is `line-length = 100`, `target-version = "py311"`, lint select `["E", "F", "I", "UP", "B"]`. Run `uv run ruff check .` before every commit.
- No changes to `app/`. No new ADR. No `CONTEXT.md` change.
- The page must work from `file://` — no `fetch()`, no external stylesheets, fonts, or images.
- `render_profile()` must always be called with a **pinned** `today`, never `date.today()`. Each state uses its own consultation date. A generator that reads the wall clock makes the drift test fail on birthday boundaries.
- Item IDs are produced by the real code, never hand-typed: prefixes are `c` chronic_conditions, `a` allergies, `m` medications, `h` habits, `o` ongoing_complaints (`app/memory/health_profile.py:26`).
- The client is synthetic. The page must carry the line `ข้อมูลผู้รับบริการในหน้านี้เป็นตัวอย่างสมมติ ไม่ใช่ข้อมูลผู้ใช้จริง`.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/build_client_record_demo.py` | The four consultations (turns, entries, ops) + `build_states()` running real `apply_ops`/`render_profile` + `inject()` + `main()` |
| `docs/client-record-walkthrough.html` | Hand-authored page: layout, styling, render JS. Data lives between `<!-- DATA:BEGIN -->` / `<!-- DATA:END -->` |
| `tests/test_client_record_demo.py` | State-shape tests, injection tests, and the staleness guard |

`scripts/` has no `__init__.py` and does not need one — the repo root is on `sys.path` under pytest, so `from scripts.build_client_record_demo import ...` resolves as an implicit namespace package. This was verified empirically; do not add `scripts/__init__.py`.

---

### Task 1: Generator — the four consultation states

**Files:**
- Create: `scripts/build_client_record_demo.py`
- Test: `tests/test_client_record_demo.py`

**Interfaces:**
- Consumes: `app.memory.health_profile.apply_ops`, `app.memory.health_profile.empty_profile`, `app.memory.profile_render.render_profile`, `app.models.profile.ProfileOp`, `app.models.schemas.HealthRecordEntry`, `TongueAssessment`, `TongueDescription`
- Produces: `build_states() -> list[dict]` — one dict per consultation with keys `index`, `date`, `label`, `kind`, `turns`, `gate`, `entry`, `ops`, `profile_before`, `profile_after`, `rendered_before`, `rendered_after`, `changed`

- [ ] **Step 1: Write the failing test**

Create `tests/test_client_record_demo.py`:

```python
from scripts.build_client_record_demo import build_states


def test_four_consultations_in_order():
    states = build_states()
    assert [state["index"] for state in states] == [1, 2, 3, 4]
    assert [state["date"] for state in states] == [
        "2026-05-02",
        "2026-05-20",
        "2026-06-15",
        "2026-07-08",
    ]


def test_first_consultation_fills_an_empty_folder():
    first = build_states()[0]
    assert "ยังไม่มีข้อมูล" in first["rendered_before"]
    assert "ข้อมูลที่ยังขาด" in first["rendered_before"]
    assert "อายุ 28 ปี" in first["rendered_after"]
    assert "ธาตุเจ้าเรือน: ไฟ" in first["rendered_after"]
    assert first["changed"]["added"] == ["h1", "o1"]


def test_tongue_photo_consultation_is_the_only_one_with_an_assessment():
    states = build_states()
    with_tongue = [s for s in states if s["entry"] and s["entry"]["tongue"]]
    assert [s["index"] for s in with_tongue] == [2]
    assert with_tongue[0]["entry"]["tongue"]["description"]["body_color"] == "แดง"
    assert with_tongue[0]["changed"] == {
        "added": ["a1"],
        "updated": ["o1"],
        "removed": [],
    }


def test_discarded_consultation_writes_nothing():
    third = build_states()[2]
    assert third["gate"]["has_health_content"] is False
    assert third["entry"] is None
    assert third["ops"] == []
    assert third["profile_before"] == third["profile_after"]
    assert third["changed"] == {"added": [], "updated": [], "removed": []}


def test_resolved_complaint_is_removed_but_its_id_is_never_reused():
    final = build_states()[-1]
    assert final["profile_after"]["ongoing_complaints"] == []
    assert final["profile_after"]["id_counters"]["ongoing_complaints"] == 1
    assert final["changed"]["removed"] == ["o1"]
    assert final["changed"]["updated"] == ["h1"]
    assert sorted(final["changed"]["added"]) == ["c1", "m1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_client_record_demo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.build_client_record_demo'`

- [ ] **Step 3: Write the generator**

Create `scripts/build_client_record_demo.py`:

```python
"""Build the data for docs/client-record-walkthrough.html.

Follows one synthetic client across four consultations, running the four
hand-authored op lists through the *real* apply_ops() and render_profile()
so the page shows what the system actually produces -- not hand-typed
strings that drift when the renderer changes (see the design spec at
docs/superpowers/specs/2026-08-19-client-record-walkthrough-design.md).

The client is fictional. Op selection is authored, as it must be for a
fixed narrative; what is real is the projection and the rendering.

Run:
    uv run python scripts/build_client_record_demo.py
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.memory.health_profile import apply_ops, empty_profile
from app.memory.profile_render import render_profile
from app.models.profile import LIST_FIELDS, HealthProfile, ProfileOp
from app.models.schemas import (
    HealthRecordEntry,
    TongueAssessment,
    TongueDescription,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE_PATH = REPO_ROOT / "docs" / "client-record-walkthrough.html"

BEGIN_MARKER = "<!-- DATA:BEGIN -->"
END_MARKER = "<!-- DATA:END -->"

CLIENT_ID = "U4af1c9b07e3d5628a1f0c4f9b6d2ae21"
CLIENT_DISPLAY_ID = "U4af1…ae21"
BIRTH_DATE = date(1998, 3, 14)


@dataclass(frozen=True)
class Consultation:
    """One authored consultation: what was said, what got written, what changed."""

    index: int
    day: date
    label: str
    kind: str  # "text" | "image" | "discarded"
    turns: list[dict]
    has_health_content: bool
    entry: HealthRecordEntry | None
    ops: list[ProfileOp]


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)


C1_DAY = date(2026, 5, 2)
C2_DAY = date(2026, 5, 20)
C3_DAY = date(2026, 6, 15)
C4_DAY = date(2026, 7, 8)

CONSULTATIONS = [
    Consultation(
        index=1,
        day=C1_DAY,
        label="1 · 2 พ.ค.",
        kind="text",
        turns=[
            {
                "role": "user",
                "text": "สวัสดีค่ะ ช่วงนี้นอนไม่หลับมาสองอาทิตย์แล้ว "
                "ตื่นตอนตีสามเกือบทุกคืน แล้วหลับต่อไม่ได้เลยค่ะ",
            },
            {
                "role": "advisor",
                "text": "สวัสดีค่ะ ขอถามเพิ่มนะคะ ปกติดื่มชาหรือกาแฟช่วงบ่าย-เย็นไหมคะ "
                "และรบกวนขอวันเกิดกับเพศด้วยค่ะ จะได้ดูธาตุเจ้าเรือนให้ถูกต้อง",
            },
            {
                "role": "user",
                "text": "ดื่มกาแฟวันละ 3 แก้วค่ะ แก้วสุดท้ายประมาณบ่ายสาม "
                "เกิด 14 มีนาคม 2541 เพศหญิงค่ะ",
            },
            {
                "role": "advisor",
                "text": "ขอบคุณค่ะ มีอาการปากแห้งคอแห้งตอนตื่นนอนด้วยไหมคะ",
            },
            {"role": "user", "text": "มีค่ะ ตื่นมาปากแห้งคอแห้งแทบทุกเช้าเลย"},
            {
                "role": "advisor",
                "text": "ธาตุเจ้าเรือนของคุณคือธาตุไฟค่ะ อาการที่เล่ามาเข้าได้กับภาวะไฟกำเริบ "
                "แนะนำลดกาแฟเหลือวันละ 1 แก้วและไม่ดื่มหลังเที่ยง ดื่มน้ำอุ่นก่อนนอน "
                "และเข้านอนเวลาเดิมทุกคืนค่ะ",
            },
        ],
        has_health_content=True,
        entry=HealthRecordEntry(
            user_id=CLIENT_ID,
            consultation_date=_at(C1_DAY),
            chief_complaint="นอนไม่หลับ ตื่นกลางดึกต่อเนื่อง 2 สัปดาห์",
            symptoms=[
                "นอนไม่หลับ",
                "ตื่นประมาณตี 3 แล้วหลับต่อไม่ได้",
                "ปากแห้งคอแห้งตอนตื่นนอน",
            ],
            tongue=None,
            advice_given="ลดกาแฟเหลือวันละ 1 แก้วและไม่ดื่มหลังเที่ยง "
            "ดื่มน้ำอุ่นก่อนนอน เข้านอนเวลาเดิมทุกคืน "
            "หากอาการไม่ดีขึ้นใน 2 สัปดาห์แนะนำพบแพทย์",
            conversation_summary="ผู้รับบริการหญิง อายุ 28 ปี ธาตุเจ้าเรือนไฟ "
            "ปรึกษาเรื่องนอนไม่หลับ ตื่นตี 3 ต่อเนื่อง 2 สัปดาห์ "
            "ร่วมกับปากแห้งคอแห้งตอนเช้า ดื่มกาแฟวันละ 3 แก้ว แก้วสุดท้ายบ่ายสาม",
        ),
        ops=[
            ProfileOp(op="set_birth_date", text="1998-03-14"),
            ProfileOp(op="set_sex", text="หญิง"),
            ProfileOp(
                op="add",
                field="habits",
                text="ดื่มกาแฟวันละ 3 แก้ว แก้วสุดท้ายบ่ายสาม",
            ),
            ProfileOp(
                op="add",
                field="ongoing_complaints",
                text="นอนไม่หลับ ตื่นประมาณตี 3",
            ),
        ],
    ),
    Consultation(
        index=2,
        day=C2_DAY,
        label="2 · 20 พ.ค. 📷",
        kind="image",
        turns=[
            {"role": "user", "text": "[ส่งรูปลิ้น]", "attachment": "tongue"},
            {
                "role": "advisor",
                "text": "จากภาพลิ้น: ลิ้นแดง ปลายลิ้นแดงจัด ฝ้าขาวบาง ผิวลิ้นค่อนข้างแห้ง "
                "และมีรอยแตกตื้นกลางลิ้น เข้าได้กับภาวะธาตุไฟกำเริบค่ะ",
            },
            {
                "role": "user",
                "text": "ตอนนี้ลดกาแฟเหลือวันละ 2 แก้วแล้วค่ะ รู้สึกหลับง่ายขึ้นนิดหน่อย "
                "แต่ยังตื่นกลางดึกอยู่",
            },
            {
                "role": "advisor",
                "text": "ดีขึ้นแล้วค่ะ แนะนำอาหารรสเย็น เช่น ฟักเขียว แตงกวา น้ำใบเตย "
                "เลี่ยงของทอดและรสจัดค่ะ",
            },
            {"role": "user", "text": "แพ้กุ้งนะคะ กินไม่ได้"},
            {"role": "advisor", "text": "รับทราบค่ะ จะเลี่ยงเมนูกุ้งให้ทั้งหมดนะคะ"},
        ],
        has_health_content=True,
        entry=HealthRecordEntry(
            user_id=CLIENT_ID,
            consultation_date=_at(C2_DAY),
            chief_complaint="ติดตามอาการนอนไม่หลับ พร้อมส่งภาพลิ้นเพื่อประเมิน",
            symptoms=["ยังตื่นกลางดึก", "หลับง่ายขึ้นเล็กน้อยหลังลดกาแฟ"],
            tongue=TongueAssessment(
                description=TongueDescription(
                    body_color="แดง",
                    body_shape="ปกติ ปลายลิ้นแดงจัด",
                    coating_color="ขาว",
                    coating_thickness="บาง",
                    moisture="แห้ง",
                    cracks=True,
                    teeth_marks=False,
                    notes="รอยแตกตื้นบริเวณกลางลิ้น",
                    quality="clear",
                ),
                assessment_text="ลิ้นแดง ปลายลิ้นแดงจัด ฝ้าขาวบาง และผิวลิ้นแห้ง "
                "เข้าได้กับภาวะธาตุไฟกำเริบ สอดคล้องกับอาการนอนไม่หลับ "
                "และปากแห้งคอแห้งที่เล่ามาในครั้งก่อน",
            ),
            advice_given="แนะนำอาหารรสเย็น เช่น ฟักเขียว แตงกวา น้ำใบเตย "
            "เลี่ยงของทอดและรสจัด เลี่ยงเมนูกุ้งเนื่องจากแพ้ และลดกาแฟต่อเนื่อง",
            conversation_summary="ส่งภาพลิ้น ประเมินได้ลิ้นแดง ฝ้าขาวบาง ผิวแห้ง "
            "มีรอยแตกกลางลิ้น เข้าได้กับธาตุไฟกำเริบ "
            "ลดกาแฟเหลือวันละ 2 แก้ว หลับง่ายขึ้นเล็กน้อยแต่ยังตื่นกลางดึก แจ้งว่าแพ้กุ้ง",
        ),
        ops=[
            ProfileOp(op="add", field="allergies", text="แพ้กุ้ง"),
            ProfileOp(
                op="update",
                field="ongoing_complaints",
                item_id="o1",
                text="นอนไม่หลับ ตื่นประมาณตี 3 (หลับง่ายขึ้นเล็กน้อยหลังลดกาแฟ)",
            ),
        ],
    ),
    Consultation(
        index=3,
        day=C3_DAY,
        label="3 · 15 มิ.ย. ✕",
        kind="discarded",
        turns=[
            {"role": "user", "text": "วันนี้ฝนตกหนักมากเลยค่ะ รถติดสุด ๆ"},
            {
                "role": "advisor",
                "text": "ขอบคุณที่แวะมาคุยค่ะ ถ้ามีอาการอะไรอยากปรึกษาบอกได้เลยนะคะ",
            },
            {"role": "user", "text": "555 ไว้จะมาถามเรื่องสุขภาพนะคะ"},
        ],
        has_health_content=False,
        entry=None,
        ops=[],
    ),
    Consultation(
        index=4,
        day=C4_DAY,
        label="4 · 8 ก.ค.",
        kind="text",
        turns=[
            {
                "role": "user",
                "text": "กลับมาอัปเดตค่ะ ตอนนี้หลับได้ตลอดคืนแล้ว "
                "ไม่ตื่นกลางดึกมาสามสัปดาห์แล้ว",
            },
            {"role": "advisor", "text": "ดีใจด้วยค่ะ ตอนนี้ดื่มกาแฟวันละกี่แก้วแล้วคะ"},
            {
                "role": "user",
                "text": "เหลือวันละแก้วเดียว ไม่ดื่มหลังเที่ยงแล้วค่ะ "
                "แต่ยังเป็นไมเกรนอยู่ เป็นมาตั้งแต่เด็ก เวลาปวดหัวก็กินพาราเซตามอล",
            },
            {
                "role": "advisor",
                "text": "รับทราบค่ะ แนะนำให้คงเวลานอนเดิมและการลดกาแฟไว้ "
                "ส่วนไมเกรนลองสังเกตสิ่งกระตุ้น หากปวดถี่ขึ้นหรือรุนแรงขึ้นแนะนำพบแพทย์ค่ะ",
            },
        ],
        has_health_content=True,
        entry=HealthRecordEntry(
            user_id=CLIENT_ID,
            consultation_date=_at(C4_DAY),
            chief_complaint="อาการนอนไม่หลับหายแล้ว มาอัปเดตอาการ",
            symptoms=["หลับได้ตลอดคืนต่อเนื่อง 3 สัปดาห์"],
            tongue=None,
            advice_given="คงเวลานอนเดิมและคงการลดกาแฟไว้ "
            "สำหรับไมเกรนแนะนำสังเกตสิ่งกระตุ้น หากปวดถี่ขึ้นหรือรุนแรงขึ้นให้พบแพทย์",
            conversation_summary="รายงานว่านอนหลับได้ตลอดคืนต่อเนื่อง 3 สัปดาห์ "
            "ถือว่าอาการนอนไม่หลับหายแล้ว ลดกาแฟเหลือวันละ 1 แก้วและไม่ดื่มหลังเที่ยง "
            "แจ้งเพิ่มว่าเป็นไมเกรนตั้งแต่เด็ก ใช้พาราเซตามอลเวลาปวดหัว",
        ),
        ops=[
            ProfileOp(op="remove", field="ongoing_complaints", item_id="o1"),
            ProfileOp(
                op="update",
                field="habits",
                item_id="h1",
                text="ลดกาแฟเหลือวันละ 1 แก้ว ไม่ดื่มหลังเที่ยง",
            ),
            ProfileOp(
                op="add", field="chronic_conditions", text="ไมเกรน เป็นมาตั้งแต่เด็ก"
            ),
            ProfileOp(op="add", field="medications", text="พาราเซตามอลเวลาปวดหัว"),
        ],
    ),
]

def _items_by_id(profile: HealthProfile) -> dict[str, str]:
    return {
        item.id: item.text
        for field in LIST_FIELDS
        for item in getattr(profile, field)
    }


def _diff(before: HealthProfile, after: HealthProfile) -> dict[str, list[str]]:
    """Which item IDs were added, updated, or removed -- derived, never authored."""
    old = _items_by_id(before)
    new = _items_by_id(after)
    return {
        "added": sorted(key for key in new if key not in old),
        "updated": sorted(key for key in new if key in old and new[key] != old[key]),
        "removed": sorted(key for key in old if key not in new),
    }


def build_states() -> list[dict]:
    """Replay the four consultations through the real projection and renderer."""
    profile = empty_profile(CLIENT_ID, _at(C1_DAY))
    states: list[dict] = []

    for consultation in CONSULTATIONS:
        moment = _at(consultation.day)
        before = profile
        if consultation.ops:
            profile, _applied, rejected = apply_ops(
                before, consultation.ops, noted_at=moment, now=moment
            )
            if rejected:
                raise ValueError(
                    f"consultation {consultation.index} has rejected ops: {rejected}"
                )

        states.append(
            {
                "index": consultation.index,
                "date": consultation.day.isoformat(),
                "label": consultation.label,
                "kind": consultation.kind,
                "turns": consultation.turns,
                "gate": {"has_health_content": consultation.has_health_content},
                "entry": (
                    json.loads(consultation.entry.model_dump_json())
                    if consultation.entry
                    else None
                ),
                "ops": [op.model_dump() for op in consultation.ops],
                "profile_before": json.loads(before.model_dump_json()),
                "profile_after": json.loads(profile.model_dump_json()),
                "rendered_before": render_profile(before, today=consultation.day),
                "rendered_after": render_profile(profile, today=consultation.day),
                "changed": _diff(before, profile),
            }
        )

    return states
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client_record_demo.py -v`
Expected: all 5 tests PASS.

If `test_first_consultation_fills_an_empty_folder` fails on `added == ["h1", "o1"]`, the `_diff` sort is alphabetical — `h1` sorts before `o1`, so this is correct; a failure means the op order or field names are wrong, not the sort.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check scripts/build_client_record_demo.py tests/test_client_record_demo.py
git add scripts/build_client_record_demo.py tests/test_client_record_demo.py
git commit -m "feat: generate Client Record walkthrough states from the real projection"
```

---

### Task 2: Generator — marker injection and CLI

**Files:**
- Modify: `scripts/build_client_record_demo.py` (append)
- Test: `tests/test_client_record_demo.py` (append)

**Interfaces:**
- Consumes: `build_states()` from Task 1
- Produces: `render_payload(states: list[dict]) -> str`, `inject(html: str, payload: str) -> str`, `main() -> None`, and the module constants `PAGE_PATH`, `BEGIN_MARKER`, `END_MARKER`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_client_record_demo.py`:

```python
import pytest

from scripts.build_client_record_demo import (
    BEGIN_MARKER,
    END_MARKER,
    inject,
    render_payload,
)

SKELETON = f"before\n{BEGIN_MARKER}\nold payload\n{END_MARKER}\nafter\n"


def test_inject_replaces_everything_between_the_markers():
    result = inject(SKELETON, "new payload")
    assert "old payload" not in result
    assert "new payload" in result
    assert result.startswith("before\n")
    assert result.endswith("after\n")


def test_inject_is_idempotent():
    once = inject(SKELETON, "new payload")
    assert inject(once, "new payload") == once


def test_inject_rejects_a_page_without_markers():
    with pytest.raises(ValueError, match="marker"):
        inject("<html>no markers</html>", "new payload")


def test_payload_is_a_script_tag_of_valid_json():
    payload = render_payload(build_states())
    assert payload.startswith("<script>")
    assert payload.rstrip().endswith("</script>")
    body = payload[payload.index("[") : payload.rindex("]") + 1]
    assert len(json.loads(body)) == 4
```

Add `import json` to the top of the test file if it is not already there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client_record_demo.py -v`
Expected: FAIL with `ImportError: cannot import name 'inject'`

- [ ] **Step 3: Implement injection and the CLI**

Append to `scripts/build_client_record_demo.py`:

```python
def render_payload(states: list[dict]) -> str:
    """The data block that sits between the markers, as an inline script tag."""
    body = json.dumps(states, ensure_ascii=False, indent=2)
    return f"<script>\nconst STATES = {body};\n</script>"


def inject(html: str, payload: str) -> str:
    """Replace everything between the markers. Raises if the page lost them."""
    start = html.find(BEGIN_MARKER)
    end = html.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"page is missing the {BEGIN_MARKER} / {END_MARKER} marker pair"
        )
    head = html[: start + len(BEGIN_MARKER)]
    tail = html[end:]
    return f"{head}\n{payload}\n{tail}"


def main() -> None:
    page = PAGE_PATH.read_text(encoding="utf-8")
    PAGE_PATH.write_text(
        inject(page, render_payload(build_states())), encoding="utf-8"
    )
    print(f"wrote {PAGE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client_record_demo.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check scripts/build_client_record_demo.py tests/test_client_record_demo.py
git add scripts/build_client_record_demo.py tests/test_client_record_demo.py
git commit -m "feat: inject walkthrough data into the page between markers"
```

---

### Task 3: The walkthrough page

**Files:**
- Create: `docs/client-record-walkthrough.html`

**Interfaces:**
- Consumes: the global `STATES` array injected by `render_payload()` — an array of 4 objects with the keys listed in Task 1
- Produces: nothing importable; a static page

Read `docs/message-flow.html` before starting and copy its `:root` token block verbatim so the two pages look like one system.

- [ ] **Step 1: Write the page skeleton with markers**

Create `docs/client-record-walkthrough.html`. Write it in full; the structure below is the whole file apart from the data block, which Step 2 injects.

```html
<title>TTM Advisor — Client Record Walkthrough</title>
<style>
  /*
    Palette tokens copied verbatim from message-flow.html so the two pages
    read as one system. message-flow.html has already spent blue/amber/purple
    on deterministic/LLM-scored/agentic, so change-type here is carried by
    GLYPH + RULE STYLE, not hue -- reusing those hues would imply a claim
    this page is not making.
  */
  :root {
    --ink: #1f2a37;
    --muted: #5b6672;
    --paper: #f5f7fa;
    --surface: #ffffff;
    --line: #c7cdd6;
    --accent: #3d5a80;
    --added: #2f855a;
    --removed: #c53030;
  }

  * { box-sizing: border-box; }
  html, body { max-width: 100%; }
  body {
    margin: 0;
    padding: 1.5rem;
    background: var(--paper);
    color: var(--ink);
    font-family: "IBM Plex Sans Thai", "Noto Sans Thai", system-ui, sans-serif;
    line-height: 1.55;
  }
  h1 { font-size: 1.5rem; font-weight: 600; margin: 0 0 .35rem; }
  .standfirst { color: var(--muted); font-size: .9rem; max-width: 62ch; margin: 0 0 .35rem; }
  .synthetic {
    color: var(--muted); font-size: .8rem; font-style: italic;
    margin: 0 0 1rem;
  }
  .label {
    text-transform: uppercase; font-size: .68rem; font-weight: 700;
    letter-spacing: .08em; color: var(--muted); margin: 0 0 .5rem;
  }

  nav { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem; }
  nav button {
    font: inherit; font-size: .85rem; padding: .4rem .8rem; cursor: pointer;
    background: var(--surface); color: var(--ink);
    border: 1px solid var(--line); border-radius: 999px;
  }
  nav button[aria-current="true"] {
    background: var(--accent); border-color: var(--accent); color: #fff;
  }
  nav button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .workspace {
    display: grid; gap: 1rem; align-items: start;
    grid-template-columns: minmax(0, 1fr) 13rem minmax(0, 1fr);
  }
  .panel {
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 8px; padding: 1rem;
  }

  .turn { margin-bottom: .6rem; display: flex; }
  .turn.user { justify-content: flex-end; }
  .bubble {
    max-width: 85%; padding: .5rem .75rem; border-radius: 12px;
    font-size: .87rem; border: 1px solid var(--line);
  }
  .turn.user .bubble { background: #eaf1f8; border-color: #c6d6e6; }
  .turn.advisor .bubble { background: var(--paper); }

  .close-divider {
    display: flex; align-items: center; gap: .6rem;
    color: var(--muted); font-size: .75rem; margin: 1rem 0 .75rem;
  }
  .close-divider::before, .close-divider::after {
    content: ""; flex: 1; height: 1px; background: var(--line);
  }
  .gate { font-size: .78rem; font-weight: 700; padding: .25rem .6rem;
          border-radius: 4px; display: inline-block; margin-bottom: .75rem; }
  .gate.pass { background: #e6f4ea; color: var(--added); }
  .gate.fail { background: #fdecea; color: var(--removed); }

  .field { margin-bottom: .5rem; font-size: .85rem; }
  .field > .k { color: var(--muted); font-family: ui-monospace, monospace;
                font-size: .76rem; display: block; }
  .nested { border-left: 2px solid var(--line); padding-left: .75rem; margin-left: .25rem; }

  .ops { list-style: none; margin: 0; padding: 0; }
  .ops li {
    font-family: ui-monospace, monospace; font-size: .74rem;
    padding: .35rem .5rem; margin-bottom: .35rem;
    background: var(--surface); border: 1px solid var(--line); border-radius: 4px;
    word-break: break-word;
  }
  .ops-empty { color: var(--muted); font-size: .8rem; font-style: italic; }
  .arrow { text-align: center; color: var(--muted); font-size: 1.25rem; }

  .section { margin-bottom: .9rem; }
  .item {
    font-size: .85rem; padding: .25rem 0 .25rem .6rem;
    border-left: 3px solid transparent;
  }
  .item .id {
    font-family: ui-monospace, monospace; font-size: .74rem; color: var(--muted);
  }
  .item .when { color: var(--muted); font-size: .74rem; }
  .item.added { border-left-color: var(--added); }
  .item.updated { border-left-style: dashed; border-left-color: var(--muted); }
  .item.removed { border-left-color: var(--removed); text-decoration: line-through;
                  opacity: .6; }
  .mark { font-weight: 700; font-family: ui-monospace, monospace; }
  .item.added .mark { color: var(--added); }
  .item.removed .mark { color: var(--removed); }

  .unchanged {
    color: var(--muted); font-size: .85rem; font-style: italic;
    padding: .5rem 0;
  }
  .folder.dimmed { opacity: .55; }

  .prompt-strip { margin-top: 1rem; }
  .prompt-pair { display: grid; gap: 1rem; grid-template-columns: 1fr 1fr; }
  .prompt-strip .sub { color: var(--muted); font-size: .78rem; margin: 0 0 .3rem; }
  .prompt-strip pre {
    margin: 0; padding: .9rem; overflow-x: auto;
    background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
    font-family: ui-monospace, monospace; font-size: .78rem; line-height: 1.6;
    white-space: pre-wrap;
  }

  @media (max-width: 900px) {
    .workspace, .prompt-pair { grid-template-columns: minmax(0, 1fr); }
    .arrow { transform: rotate(90deg); }
  }
</style>

<h1>Client Record — a walkthrough</h1>
<p class="standfirst">
  ตามผู้รับบริการหนึ่งรายผ่าน 4 consultations ดูว่าแต่ละครั้งเขียน
  <strong>Health Record entry</strong> อะไรลงไป และ
  <strong>แฟ้มผู้รับบริการ (Health Profile)</strong> ค่อย ๆ ก่อตัวขึ้นจาก entry เหล่านั้นอย่างไร
  ตาม ADR 0003 แฟ้มนี้เป็น projection ที่ถูก patch ทีละรายการเมื่อ consultation ปิด
  ไม่เคยถูกเขียนโดย Advisor เอง
</p>
<p class="synthetic">
  ข้อมูลผู้รับบริการในหน้านี้เป็นตัวอย่างสมมติ ไม่ใช่ข้อมูลผู้ใช้จริง
  (ข้อความที่แสดงในแถบล่างมาจากฟังก์ชัน <code>render_profile()</code> จริงของระบบ)
</p>

<nav id="nav" aria-label="Consultations"></nav>

<div class="workspace">
  <section class="panel" aria-labelledby="lc">
    <p class="label" id="lc">The Consultation</p>
    <div id="consultation"></div>
  </section>

  <section aria-labelledby="lo">
    <p class="label" id="lo">Ops applied at close</p>
    <div id="ops"></div>
    <p class="arrow" aria-hidden="true">&rarr;</p>
  </section>

  <section class="panel folder" id="folder-panel" aria-labelledby="lf">
    <p class="label" id="lf">แฟ้มผู้รับบริการ · Client Record</p>
    <div id="folder"></div>
  </section>
</div>

<div class="prompt-strip">
  <p class="label">What the Advisor reads — <code>render_profile()</code></p>
  <div class="prompt-pair">
    <div><p class="sub">ก่อน consultation นี้</p><pre id="rendered-before"></pre></div>
    <div><p class="sub">หลังปิด consultation นี้</p><pre id="rendered-after"></pre></div>
  </div>
</div>

<!-- DATA:BEGIN -->
<!-- DATA:END -->

<script>
  const SECTIONS = [
    ["chronic_conditions", "โรคประจำตัว"],
    ["allergies", "ประวัติแพ้"],
    ["medications", "ยา/สมุนไพรที่ใช้ประจำ"],
    ["habits", "พฤติกรรม"],
    ["ongoing_complaints", "อาการที่ติดตามอยู่"],
  ];
  const MARKS = { added: "+", updated: "±", removed: "−" };

  let current = 0;

  const esc = (s) => String(s).replace(/[&<>]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

  function markFor(state, id) {
    for (const kind of ["added", "updated", "removed"]) {
      if (state.changed[kind].includes(id)) return kind;
    }
    return "";
  }

  function renderConsultation(state) {
    const turns = state.turns.map((t) =>
      `<div class="turn ${t.role}"><div class="bubble">${esc(t.text)}</div></div>`
    ).join("");

    const gate = state.gate.has_health_content
      ? `<span class="gate pass">Relevance Gate: has_health_content = true</span>`
      : `<span class="gate fail">Relevance Gate: has_health_content = false</span>`;

    let entry;
    if (!state.entry) {
      entry = `<p class="unchanged">ไม่มีการเขียน Health Record entry — Working Buffer ถูกลบทิ้ง</p>`;
    } else {
      const e = state.entry;
      const rows = [
        ["chief_complaint", esc(e.chief_complaint)],
        ["symptoms", e.symptoms.map(esc).join(" · ")],
        ["advice_given", esc(e.advice_given)],
        ["conversation_summary", esc(e.conversation_summary)],
      ].map(([k, v]) => `<div class="field"><span class="k">${k}</span>${v}</div>`).join("");

      let tongue = "";
      if (e.tongue) {
        const d = e.tongue.description;
        const desc = Object.entries(d)
          .map(([k, v]) => `<div class="field"><span class="k">${k}</span>${esc(v)}</div>`)
          .join("");
        tongue =
          `<div class="field"><span class="k">tongue.assessment_text</span>` +
          `${esc(e.tongue.assessment_text)}</div>` +
          `<div class="nested"><p class="label">tongue.description</p>${desc}</div>`;
      }
      entry = rows + tongue;
    }

    return turns +
      `<p class="close-divider">ปิด Consultation (เงียบเกิน 6 ชม.)</p>` +
      gate + entry;
  }

  function renderOps(state) {
    if (!state.ops.length) return `<p class="ops-empty">ไม่มี ops — แฟ้มไม่ถูกแตะเลย</p>`;
    return `<ul class="ops">` + state.ops.map((op) => {
      const parts = [op.op];
      if (op.field) parts.push(op.field);
      if (op.item_id) parts.push(`[${op.item_id}]`);
      if (op.text) parts.push(`"${op.text}"`);
      return `<li>${esc(parts.join(" "))}</li>`;
    }).join("") + `</ul>`;
  }

  function renderFolder(state) {
    const after = state.profile_after;
    const before = state.profile_before;

    const head = [];
    if (after.birth_date) head.push(`เกิด ${after.birth_date}`);
    if (after.sex) head.push(`เพศ ${after.sex}`);
    const header = head.length
      ? `<div class="section"><p class="label">identity</p><div class="item">${esc(head.join(" · "))}</div></div>`
      : "";

    const body = SECTIONS.map(([field, thai]) => {
      const items = after[field].slice();
      const gone = before[field].filter(
        (b) => !after[field].some((a) => a.id === b.id)
      );
      const all = items.concat(gone.map((g) => ({ ...g, _gone: true })));
      if (!all.length) return "";
      const rows = all.map((item) => {
        const kind = item._gone ? "removed" : markFor(state, item.id);
        const mark = kind ? `<span class="mark">${MARKS[kind]}</span> ` : "";
        return `<div class="item ${kind}">${mark}` +
          `<span class="id">[${esc(item.id)}]</span> ${esc(item.text)} ` +
          `<span class="when">บันทึก ${esc(item.noted_at.slice(0, 10))}</span></div>`;
      }).join("");
      return `<div class="section"><p class="label">${thai}</p>${rows}</div>`;
    }).join("");

    if (!header && !body) return `<p class="unchanged">แฟ้มว่าง — ยังไม่มีข้อมูล</p>`;
    return header + body;
  }

  function show(index) {
    current = index;
    const state = STATES[index];

    document.getElementById("consultation").innerHTML = renderConsultation(state);
    document.getElementById("ops").innerHTML = renderOps(state);
    document.getElementById("folder").innerHTML =
      (state.kind === "discarded" ? `<p class="unchanged">แฟ้มไม่เปลี่ยนแปลง</p>` : "") +
      renderFolder(state);
    document.getElementById("folder-panel").classList.toggle(
      "dimmed", state.kind === "discarded");
    document.getElementById("rendered-before").textContent = state.rendered_before;
    document.getElementById("rendered-after").textContent = state.rendered_after;

    [...document.querySelectorAll("#nav button")].forEach((b, i) =>
      b.setAttribute("aria-current", String(i === index)));
  }

  document.getElementById("nav").innerHTML = STATES.map((s, i) =>
    `<button type="button" data-index="${i}">${esc(s.label)}</button>`).join("");
  document.getElementById("nav").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (button) show(Number(button.dataset.index));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight") show(Math.min(current + 1, STATES.length - 1));
    if (event.key === "ArrowLeft") show(Math.max(current - 1, 0));
  });

  show(0);
</script>
```

- [ ] **Step 2: Generate the data into the page**

Run: `uv run python scripts/build_client_record_demo.py`
Expected: `wrote docs/client-record-walkthrough.html`

- [ ] **Step 3: Verify every state renders**

Open the page and step through all four consultations, checking each of these:

1. State 1 — แฟ้ม starts empty, ends with identity + `[h1]` + `[o1]`, both marked `+` with a solid green rule.
2. State 2 — the entry card shows `tongue.assessment_text` and a nested `tongue.description` with all nine fields; `[a1]` marked `+`, `[o1]` marked `±` with a dashed rule.
3. State 3 — right pane dimmed under `แฟ้มไม่เปลี่ยนแปลง`, ops column reads `ไม่มี ops`, gate badge red, no entry card.
4. State 4 — `[o1]` struck through in red with `−`, `[h1]` marked `±`, `[c1]` and `[m1]` marked `+`, and the อาการที่ติดตามอยู่ section shows only the struck-through `o1`.
5. Bottom strip shows both renders side by side. On state 1 the left one reads
   `ยังไม่มีข้อมูลในแฟ้มผู้ใช้รายนี้` and lists `ข้อมูลที่ยังขาด: วันเกิด..., เพศ` — that
   line is what drove the Advisor's intake question in the chat above it, and it is
   gone from the right one. On state 3 both sides are identical.
6. ← / → arrow keys move between states.
7. Narrow the window below 900px: the three columns stack and the arrow rotates.

- [ ] **Step 4: Commit**

```bash
git add docs/client-record-walkthrough.html
git commit -m "docs: Client Record walkthrough page"
```

---

### Task 4: Staleness guard

**Files:**
- Modify: `tests/test_client_record_demo.py` (append)

**Interfaces:**
- Consumes: `PAGE_PATH`, `inject`, `render_payload`, `build_states` from Tasks 1–2; the committed `docs/client-record-walkthrough.html` from Task 3

- [ ] **Step 1: Write the failing test**

Append to `tests/test_client_record_demo.py`:

```python
from scripts.build_client_record_demo import PAGE_PATH


def test_committed_page_matches_a_fresh_generation():
    """Fails the moment render_profile(), the section labels, or the ID
    prefixes change -- the only drift that can make the page lie."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    assert inject(page, render_payload(build_states())) == page, (
        "docs/client-record-walkthrough.html is stale; regenerate it with "
        "`uv run python scripts/build_client_record_demo.py`"
    )
```

- [ ] **Step 2: Run it and confirm it passes on a fresh page**

Run: `uv run pytest tests/test_client_record_demo.py::test_committed_page_matches_a_fresh_generation -v`
Expected: PASS (Task 3 Step 2 already regenerated the page).

- [ ] **Step 3: Verify the guard actually catches drift**

Prove the test can fail, rather than trusting that it can:

```bash
python3 - <<'EOF'
import pathlib
p = pathlib.Path("docs/client-record-walkthrough.html")
p.write_text(p.read_text(encoding="utf-8").replace("อายุ 28 ปี", "อายุ 99 ปี", 1), encoding="utf-8")
EOF
uv run pytest tests/test_client_record_demo.py::test_committed_page_matches_a_fresh_generation -q
```

Expected: FAIL with the "is stale" message. Then restore:

```bash
uv run python scripts/build_client_record_demo.py
uv run pytest tests/test_client_record_demo.py -q
```

Expected: all 10 tests PASS.

- [ ] **Step 4: Run the whole suite and lint**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: the full suite passes and ruff reports no issues.

- [ ] **Step 5: Commit**

```bash
git add tests/test_client_record_demo.py
git commit -m "test: guard the walkthrough page against renderer drift"
```
