from types import SimpleNamespace

from PIL import Image

import app.pipeline.dispatcher as dispatcher
from app.config import Settings
from app.models.schemas import TongueDescription
from app.vision.detector import CroppedTongue, TongueDetectionError


def _settings(**overrides) -> Settings:
    return Settings(
        line_channel_secret="test", line_channel_access_token="test", **overrides
    )


def _event() -> SimpleNamespace:
    return SimpleNamespace(
        source=SimpleNamespace(user_id="U1"),
        message=SimpleNamespace(id="M1"),
        reply_token="R1",
    )


def _pil_image() -> Image.Image:
    return Image.new("RGB", (16, 16), (200, 60, 60))


class _FakeMessenger:
    def __init__(self, settings) -> None:
        self.sent: list[str] = []
        self.images: list = []

    async def show_loading(self, user_id) -> None:
        return None

    async def download_content(self, message_id) -> bytes:
        return b"fake-image-bytes"

    async def reply_or_push(
        self, *, reply_token, user_id, text, topics=(), image_url=None, citation=None
    ) -> None:
        self.sent.append(text)
        self.images.append(image_url)


def _patch_common(monkeypatch):
    """Route the dispatcher's messenger to a fake, record consultation runs,
    and stub the Tongue Photo store (no real Mongo)."""
    messenger = _FakeMessenger(None)
    monkeypatch.setattr(dispatcher, "LineMessenger", lambda settings: messenger)

    consultation_inputs: list[str] = []

    async def fake_consultation(user_id, incoming_text, settings):
        consultation_inputs.append(incoming_text)
        return dispatcher.split_topic_menu("คำแนะนำจากผู้ช่วย")

    monkeypatch.setattr(dispatcher, "_run_consultation_turn", fake_consultation)

    saved: list = []
    patched: list = []

    class _FakePhotoRepo:
        def __init__(self, db) -> None:
            pass

        async def insert(self, photo) -> None:
            saved.append(photo)

        async def set_description(self, photo_id, description) -> None:
            patched.append((photo_id, description))

    monkeypatch.setattr(dispatcher, "TonguePhotoRepository", _FakePhotoRepo)
    monkeypatch.setattr(dispatcher, "get_database", lambda settings=None: None)
    return messenger, consultation_inputs, saved, patched


class _StubDetector:
    def __init__(self, settings) -> None:
        pass


class _StubDescriber:
    def __init__(self, settings) -> None:
        pass


def _description(**overrides) -> TongueDescription:
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


async def test_download_failure_sends_system_hiccup(monkeypatch):
    # Observed live 2026-07-07: a LINE content-API 404 escaped the guard and
    # the user saw the loading animation, then silence.
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def failing_download(message_id):
        raise RuntimeError("LINE content API 404")

    messenger.download_content = failing_download

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.SYSTEM_HICCUP_MESSAGE]
    assert consultation_inputs == []


async def test_loading_animation_failure_does_not_abort_turn(monkeypatch):
    # The loading animation is cosmetic -- its failure must not cost the user
    # their Tongue Assessment.
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def failing_loading(user_id):
        raise RuntimeError("loading animation rejected")

    messenger.show_loading = failing_loading

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _description()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == ["คำแนะนำจากผู้ช่วย"]
    assert len(consultation_inputs) == 1


async def test_detector_error_sends_system_hiccup_not_retake(monkeypatch):
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def failing_detect(self, image_bytes):
        raise TongueDetectionError("roboflow down")

    monkeypatch.setattr(_StubDetector, "detect_and_crop", failing_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.SYSTEM_HICCUP_MESSAGE]
    assert consultation_inputs == []


async def test_no_tongue_still_sends_retake_guidance(monkeypatch):
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def none_detect(self, image_bytes):
        return None

    monkeypatch.setattr(_StubDetector, "detect_and_crop", none_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.RETAKE_GUIDANCE]
    assert consultation_inputs == []


async def test_below_gate_crop_sends_retake_and_never_describes(monkeypatch):
    # ADR 0007: rejected crops are never described, assessed, or echoed --
    # the user-facing retake flow is unchanged.
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def below_gate_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.3, passed_gate=False)

    async def exploding_describe(self, image):
        raise AssertionError("below-gate crop must never reach the describer")

    monkeypatch.setattr(_StubDetector, "detect_and_crop", below_gate_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", exploding_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.RETAKE_GUIDANCE]
    assert consultation_inputs == []


async def test_describer_error_sends_system_hiccup(monkeypatch):
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def failing_describe(self, image):
        raise RuntimeError("vision model outage")

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", failing_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.SYSTEM_HICCUP_MESSAGE]
    assert consultation_inputs == []


async def test_happy_path_runs_consultation_with_description(monkeypatch):
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _description()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == ["คำแนะนำจากผู้ช่วย"]
    assert len(consultation_inputs) == 1
    assert "แดงเข้ม" in consultation_inputs[0]


async def test_tongue_turn_renders_thai_axis_labels_never_json_keys(monkeypatch):
    # ADR 0010, "the rendered description is the retrieval query": the
    # rendered text is what KEYWORD and the Working Buffer see, so it must
    # carry Thai axis labels -- never model_dump_json(), whose English
    # field names must not reach either.
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _description(notes="เห็นแผลเล็กน้อยที่ปลายลิ้น")

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    (turn_text,) = consultation_inputs
    assert "สี: แดงเข้ม" in turn_text
    assert "ฝ้า: ฝ้าขาวหนา" in turn_text
    assert "ขนาด: ปกติ" in turn_text
    assert "รูปร่าง: ขอบลิ้นมีรอยหยักของฟัน" in turn_text
    assert "จุดบนลิ้น: ไม่มีจุด" in turn_text
    assert "เห็นแผลเล็กน้อยที่ปลายลิ้น" in turn_text  # notes still reaches the query
    # never the schema's English field/key names -- e.g. no `"color":` etc.
    for english_key in ("color", "coating", "size", "shape", "spots", "quality"):
        assert english_key not in turn_text


async def test_gate_passed_crop_is_saved_then_description_patched(monkeypatch):
    # Insert after detect, update after describe (ADR 0007).
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _description()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    (photo,) = saved
    assert photo.user_id == "U1"
    assert photo.line_message_id == "M1"
    assert photo.confidence == 0.9
    assert photo.passed_gate is True
    assert photo.description is None  # inserted before the describer ran
    assert len(photo.photo_id) == 36  # UUID4 string, never an ObjectId
    assert len(patched) == 1
    assert patched[0][0] == photo.photo_id


async def test_below_gate_crop_is_saved_with_passed_gate_false(monkeypatch):
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def below_gate_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.3, passed_gate=False)

    monkeypatch.setattr(_StubDetector, "detect_and_crop", below_gate_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)

    await dispatcher.handle_image_message(_event(), _settings())

    (photo,) = saved
    assert photo.passed_gate is False
    assert patched == []  # rejected crops are never described
    assert messenger.sent == [dispatcher.RETAKE_GUIDANCE]
    assert messenger.images == [None]  # never echoed


async def test_photo_save_failure_is_swallowed_and_echo_skipped(monkeypatch):
    # ADR 0007: a Mongo write error must not turn a good photo turn into a
    # hiccup message -- and we never hand LINE a URL that would 404.
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    class _ExplodingRepo:
        def __init__(self, db) -> None:
            pass

        async def insert(self, photo) -> None:
            raise RuntimeError("mongo down")

    monkeypatch.setattr(dispatcher, "TonguePhotoRepository", _ExplodingRepo)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _description()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(
        _event(), _settings(public_base_url="https://tunnel.example.com")
    )

    assert messenger.sent == ["คำแนะนำจากผู้ช่วย"]  # Assessment survived
    assert messenger.images == [None]  # echo skipped, not broken


async def test_describer_outage_still_keeps_the_saved_photo(monkeypatch):
    # Previously everything was lost; now the crop is on record with a null
    # description marking exactly which stage failed (ADR 0007).
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def failing_describe(self, image):
        raise RuntimeError("vision model outage")

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", failing_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    assert len(saved) == 1
    assert patched == []
    assert messenger.sent == [dispatcher.SYSTEM_HICCUP_MESSAGE]


async def test_gate_passed_echo_carries_capability_url(monkeypatch):
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _description()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(
        _event(), _settings(public_base_url="https://tunnel.example.com/")
    )

    (photo,) = saved
    assert messenger.images == [f"https://tunnel.example.com/tongue-photos/{photo.photo_id}"]


async def test_no_public_base_url_means_no_echo(monkeypatch):
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _description()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    # Set it explicitly rather than leaning on the field default: Settings reads
    # .env (model_config env_file), so on any machine with PUBLIC_BASE_URL set --
    # i.e. any machine running the tunnel -- the default is not "".
    await dispatcher.handle_image_message(_event(), _settings(public_base_url=""))

    assert len(saved) == 1  # dataset capture is independent of the echo
    assert messenger.sent == ["คำแนะนำจากผู้ช่วย"]
    assert messenger.images == [None]
