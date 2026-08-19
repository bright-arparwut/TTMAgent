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
