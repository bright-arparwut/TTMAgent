from types import SimpleNamespace

from PIL import Image

import app.pipeline.dispatcher as dispatcher
from app.config import Settings
from app.vision.detector import CroppedTongue, TongueDetectionError


def _settings() -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test")


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

    async def show_loading(self, user_id) -> None:
        return None

    async def download_content(self, message_id) -> bytes:
        return b"fake-image-bytes"

    async def reply_or_push(self, *, reply_token, user_id, text) -> None:
        self.sent.append(text)


def _patch_common(monkeypatch) -> tuple[_FakeMessenger, list[str]]:
    """Route the dispatcher's messenger to a fake and record consultation runs."""
    messenger = _FakeMessenger(None)
    monkeypatch.setattr(dispatcher, "LineMessenger", lambda settings: messenger)

    consultation_inputs: list[str] = []

    async def fake_consultation(user_id, incoming_text, settings):
        consultation_inputs.append(incoming_text)
        return "คำแนะนำจากผู้ช่วย"

    monkeypatch.setattr(dispatcher, "_run_consultation_turn", fake_consultation)
    return messenger, consultation_inputs


class _StubDetector:
    def __init__(self, settings) -> None:
        pass


class _StubDescriber:
    def __init__(self, settings) -> None:
        pass


class _FakeDescription:
    def model_dump_json(self) -> str:
        return '{"color": "แดง"}'


async def test_download_failure_sends_system_hiccup(monkeypatch):
    # Observed live 2026-07-07: a LINE content-API 404 escaped the guard and
    # the user saw the loading animation, then silence.
    messenger, consultation_inputs = _patch_common(monkeypatch)

    async def failing_download(message_id):
        raise RuntimeError("LINE content API 404")

    messenger.download_content = failing_download

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.SYSTEM_HICCUP_MESSAGE]
    assert consultation_inputs == []


async def test_loading_animation_failure_does_not_abort_turn(monkeypatch):
    # The loading animation is cosmetic -- its failure must not cost the user
    # their Tongue Assessment.
    messenger, consultation_inputs = _patch_common(monkeypatch)

    async def failing_loading(user_id):
        raise RuntimeError("loading animation rejected")

    messenger.show_loading = failing_loading

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9)

    async def ok_describe(self, image):
        return _FakeDescription()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == ["คำแนะนำจากผู้ช่วย"]
    assert len(consultation_inputs) == 1


async def test_detector_error_sends_system_hiccup_not_retake(monkeypatch):
    messenger, consultation_inputs = _patch_common(monkeypatch)

    async def failing_detect(self, image_bytes):
        raise TongueDetectionError("roboflow down")

    monkeypatch.setattr(_StubDetector, "detect_and_crop", failing_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.SYSTEM_HICCUP_MESSAGE]
    assert consultation_inputs == []


async def test_no_tongue_still_sends_retake_guidance(monkeypatch):
    messenger, consultation_inputs = _patch_common(monkeypatch)

    async def none_detect(self, image_bytes):
        return None

    monkeypatch.setattr(_StubDetector, "detect_and_crop", none_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == [dispatcher.RETAKE_GUIDANCE]
    assert consultation_inputs == []


async def test_describer_error_sends_system_hiccup(monkeypatch):
    messenger, consultation_inputs = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9)

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
    messenger, consultation_inputs = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9)

    async def ok_describe(self, image):
        return _FakeDescription()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())

    assert messenger.sent == ["คำแนะนำจากผู้ช่วย"]
    assert len(consultation_inputs) == 1
    assert '{"color": "แดง"}' in consultation_inputs[0]
