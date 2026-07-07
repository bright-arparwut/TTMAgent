import base64
import io
import time

import pytest
from PIL import Image

import app.vision.detector as detector_module
from app.config import Settings
from app.vision.detector import CroppedTongue, TongueDetectionError, TongueDetector


def _settings(**overrides) -> Settings:
    return Settings(
        line_channel_secret="test",
        line_channel_access_token="test",
        roboflow_api_key="key",
        roboflow_workspace_name="arparwuts-workspace",
        roboflow_workflow_id="tongue-detect-crop",
        **overrides,
    )


def _jpeg_bytes(size: tuple[int, int] = (16, 16)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 60, 60)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _crop(size: tuple[int, int] = (16, 16)) -> dict:
    return {"type": "base64", "value": base64.b64encode(_jpeg_bytes(size)).decode("utf-8")}


def _prediction(confidence: float) -> dict:
    return {
        "x": 120.0,
        "y": 90.0,
        "width": 60.0,
        "height": 40.0,
        "confidence": confidence,
        "class": "tongue",
        "class_id": 0,
        "detection_id": "d1",
    }


def _response(predictions: list[dict], crops: list[dict]) -> list[dict]:
    return [
        {
            "output_tongue_crop": crops,
            "raw_predictions": {
                "predictions": predictions,
                "image": {"width": 640, "height": 480},
            },
        }
    ]


def _detector_returning(response) -> tuple[TongueDetector, dict]:
    """Detector whose workflow call returns `response`; records call kwargs."""
    detector = TongueDetector(_settings())
    recorded: dict = {}

    def fake_run_workflow(**kwargs):
        recorded.update(kwargs)
        return response

    detector._client.run_workflow = fake_run_workflow
    return detector, recorded


async def test_returns_cropped_tongue_with_confidence_on_detection():
    detector, recorded = _detector_returning(_response([_prediction(0.92)], [_crop()]))

    result = await detector.detect_and_crop(_jpeg_bytes())

    assert isinstance(result, CroppedTongue)
    assert result.confidence == 0.92
    assert result.image.size == (16, 16)
    assert recorded["workspace_name"] == "arparwuts-workspace"
    assert recorded["workflow_id"] == "tongue-detect-crop"
    assert recorded["use_cache"] is False


async def test_returns_none_when_workflow_finds_no_tongue():
    detector, _ = _detector_returning(_response([], []))

    assert await detector.detect_and_crop(_jpeg_bytes()) is None


async def test_returns_none_when_best_confidence_below_threshold():
    detector, _ = _detector_returning(_response([_prediction(0.3)], [_crop()]))

    assert await detector.detect_and_crop(_jpeg_bytes()) is None


async def test_picks_crop_paired_with_highest_confidence_prediction():
    # Top-1 filter in the workflow should prevent this, but the app-side
    # argmax pairing is the agreed insurance (crop sizes distinguish them).
    response = _response(
        [_prediction(0.6), _prediction(0.9)],
        [_crop(size=(16, 16)), _crop(size=(8, 8))],
    )
    detector, _ = _detector_returning(response)

    result = await detector.detect_and_crop(_jpeg_bytes())

    assert result is not None
    assert result.confidence == 0.9
    assert result.image.size == (8, 8)


async def test_raises_on_crop_prediction_count_mismatch():
    detector, _ = _detector_returning(
        _response([_prediction(0.9), _prediction(0.8)], [_crop()])
    )

    with pytest.raises(TongueDetectionError):
        await detector.detect_and_crop(_jpeg_bytes())


async def test_raises_on_malformed_response_missing_keys():
    detector, _ = _detector_returning([{"unexpected": "shape"}])

    with pytest.raises(TongueDetectionError):
        await detector.detect_and_crop(_jpeg_bytes())


async def test_raises_on_empty_response_list():
    detector, _ = _detector_returning([])

    with pytest.raises(TongueDetectionError):
        await detector.detect_and_crop(_jpeg_bytes())


async def test_raises_when_crop_base64_does_not_decode_to_an_image():
    bad_crop = {"type": "base64", "value": "bm90LWFuLWltYWdl"}  # "not-an-image"
    detector, _ = _detector_returning(_response([_prediction(0.9)], [bad_crop]))

    with pytest.raises(TongueDetectionError):
        await detector.detect_and_crop(_jpeg_bytes())


async def test_wraps_workflow_network_errors():
    detector = TongueDetector(_settings())

    def exploding_run_workflow(**kwargs):
        raise ConnectionError("roboflow unreachable")

    detector._client.run_workflow = exploding_run_workflow

    with pytest.raises(TongueDetectionError):
        await detector.detect_and_crop(_jpeg_bytes())


async def test_times_out_hung_workflow_call(monkeypatch):
    monkeypatch.setattr(detector_module, "WORKFLOW_TIMEOUT_SECONDS", 0.05)
    detector = TongueDetector(_settings())

    def hanging_run_workflow(**kwargs):
        time.sleep(0.5)

    detector._client.run_workflow = hanging_run_workflow

    with pytest.raises(TongueDetectionError):
        await detector.detect_and_crop(_jpeg_bytes())
