import pytest
from PIL import Image

import app.vision.describer as describer_module
from app.config import Settings
from app.models.schemas import TongueDescription
from app.vision.describer import DESCRIBE_PROMPT, VisionDescriber

AXIS_LABELS = ("สี", "ฝ้า", "ขนาด", "รูปร่าง", "จุดบนลิ้น")


def _settings(**overrides) -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test", **overrides)


@pytest.mark.parametrize("label", AXIS_LABELS)
def test_describe_prompt_names_every_axis_in_thai(label):
    assert label in DESCRIBE_PROMPT


def test_describe_prompt_shape_guidance_covers_cracks_and_teeth_marks():
    # Issue #36's addendum: the รูปร่าง field's steering draws from both
    # note 207 (pure shape) and note 210 (the cracks/teeth-marks band) --
    # #31's decision 4 folds them into the schema's `shape` field.
    assert "รอยแตก" in DESCRIBE_PROMPT
    assert "รอยหยักของฟัน" in DESCRIBE_PROMPT


def test_describe_prompt_excludes_movement_and_sublingual_veins():
    # #31/#36: a still top-side crop cannot witness either -- no prompt
    # nudge (a nudge would invite speculation about an unseen underside or
    # a still frame); `notes` is the escape hatch for the rare visible case.
    assert "การเคลื่อนไหว" not in DESCRIBE_PROMPT
    assert "หลอดเลือดใต้ลิ้น" not in DESCRIBE_PROMPT
    assert "เส้นเลือดใต้ลิ้น" not in DESCRIBE_PROMPT


def test_describe_prompt_steers_with_examples_not_enums():
    assert "ตัวอย่าง" in DESCRIBE_PROMPT


def test_describe_prompt_instructs_no_diagnosis():
    assert "วินิจฉัย" in DESCRIBE_PROMPT


class _FakeStructuredModel:
    def __init__(self) -> None:
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return TongueDescription(
            color="แดง",
            coating="ฝ้าขาวบาง",
            size="ปกติ",
            shape="ปกติ",
            spots="ไม่มีจุด",
            quality="clear",
        )


class _FakeChatModel:
    def __init__(self) -> None:
        self.structured_output_schema = None
        self.structured = _FakeStructuredModel()

    def with_structured_output(self, schema):
        self.structured_output_schema = schema
        return self.structured


async def test_describe_wires_structured_output_to_tongue_description(monkeypatch):
    fake_model = _FakeChatModel()
    monkeypatch.setattr(describer_module, "build_chat_model", lambda slot: fake_model)

    describer = VisionDescriber(_settings())
    image = Image.new("RGB", (16, 16), (200, 60, 60))

    result = await describer.describe(image)

    assert fake_model.structured_output_schema is TongueDescription
    assert isinstance(result, TongueDescription)
    sent_message = fake_model.structured.messages[0]
    assert sent_message.content[0]["text"] == DESCRIBE_PROMPT
