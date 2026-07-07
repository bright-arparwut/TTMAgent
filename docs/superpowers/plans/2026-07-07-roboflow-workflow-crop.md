# Roboflow Workflow Crop Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `TongueDetector` from the Roboflow hosted-model endpoint (+ local PIL crop) to the Roboflow serverless workflow `tongue-detect-crop`, which detects and crops server-side, while keeping the "Tongue found?" decision in app code and adding a proper failure contract to the image pipeline.

**Architecture:** The workflow returns `output_tongue_crop` (base64 crop) and `raw_predictions` (bboxes + confidences) in one round-trip. The app applies its own confidence threshold to `raw_predictions` (the documented deterministic diamond in `docs/message-flow.md`), decodes the matching crop for the Vision Describer, and distinguishes three outcomes: crop found / clean no-tongue (`None` → Thai retake guidance) / `TongueDetectionError` (→ new Thai "system hiccup" message). One guard in the dispatcher covers the detect→describe stretch so vision failures never die silently in the background task.

**Tech Stack:** Python 3.11, FastAPI, `inference-sdk` 1.3.3 (sync `run_workflow` wrapped in `asyncio.to_thread`), Pillow, pytest + pytest-asyncio (auto mode), `uv` as the runner.

## Global Constraints

- `inference-sdk` 1.3.3 has **no async workflow method** (verified) — the sync `run_workflow` must be wrapped with `asyncio.to_thread` + `asyncio.wait_for`.
- `use_cache=False` on every `run_workflow` call (user decision — console edits must take effect immediately).
- Workflow call timeout: `WORKFLOW_TIMEOUT_SECONDS = 30` module constant (not config).
- App-side `roboflow_confidence_threshold` (default 0.5) is the **only authoritative** "tongue found?" gate; the workflow's model-node threshold (~0.25, console-side) must stay below it.
- The workflow contains a top-1 detections filter (console-side); the app still pairs crop↔prediction by argmax confidence and hard-errors on list-length mismatch.
- Delete `roboflow_model_id` and `roboflow_crop_padding_ratio` (and `_crop_with_padding`) — no dead config, no rollback stubs.
- New Thai copy, exact strings:
  - System hiccup: `ขออภัยค่ะ ระบบวิเคราะห์ภาพขัดข้องชั่วคราว กรุณาลองส่งภาพอีกครั้งภายหลังนะคะ`
  - Retake guidance: unchanged (`RETAKE_GUIDANCE` in `app/pipeline/dispatcher.py:27`).
- Commit format: conventional commits, **no** Co-Authored-By / attribution lines (disabled globally in user settings).
- Run everything through `uv run` (e.g. `uv run pytest`). Ruff line length is 100.
- Roboflow console work (rename workflow to `tongue-detect-crop`, add top-1 filter, set model-node threshold ~0.25, output names `output_tongue_crop` / `raw_predictions`) is the **user's task** — the plan assumes it is done; nothing in this repo can do it.

**Workflow response contract** (one list entry per input image):

```json
[
  {
    "output_tongue_crop": [
      {"type": "base64", "value": "<cropped_tongue_image_base64>"}
    ],
    "raw_predictions": {
      "predictions": [
        {"x": 123.4, "y": 234.5, "width": 100.0, "height": 80.0,
         "confidence": 0.92, "class": "tongue", "class_id": 0, "detection_id": "..."}
      ],
      "image": {"width": 640, "height": 480}
    }
  }
]
```

---

### Task 1: Rewrite `TongueDetector` against the serverless workflow

**Files:**
- Modify: `app/config.py:40-44` (Roboflow settings block)
- Modify: `.env.example:19-23` (Roboflow env block)
- Rewrite: `app/vision/detector.py`
- Create: `tests/vision/__init__.py`
- Test: `tests/vision/test_detector.py`

**Interfaces:**
- Consumes: `Settings` from `app.config` (new fields `roboflow_workspace_name: str`, `roboflow_workflow_id: str`; existing `roboflow_api_key: str`, `roboflow_confidence_threshold: float`).
- Produces (Task 2 relies on these exact names):
  - `class TongueDetectionError(Exception)` in `app.vision.detector`
  - `class CroppedTongue(BaseModel)` with fields `image: Image.Image`, `confidence: float` (unchanged from today)
  - `TongueDetector(settings).detect_and_crop(image_bytes: bytes) -> CroppedTongue | None`, raising `TongueDetectionError` on network/timeout/contract failures
  - Module constants `ROBOFLOW_SERVERLESS_API_URL`, `WORKFLOW_TIMEOUT_SECONDS`

- [ ] **Step 1: Write the failing tests**

Create `tests/vision/__init__.py` (empty file), then `tests/vision/test_detector.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/vision/test_detector.py -v`
Expected: FAIL at import time with `ImportError: cannot import name 'TongueDetectionError'` (and `Settings` would reject `roboflow_workspace_name` if imports got further).

- [ ] **Step 3: Update the config surface**

In `app/config.py`, replace lines 40–44:

```python
    # Roboflow hosted tongue detector
    roboflow_api_key: str = ""
    roboflow_model_id: str = ""
    roboflow_confidence_threshold: float = 0.5
    roboflow_crop_padding_ratio: float = 0.12
```

with:

```python
    # Roboflow serverless workflow: tongue detect + server-side crop.
    # roboflow_confidence_threshold is the only authoritative "tongue
    # found?" gate -- see docs/adr/0004-serverless-workflow-crop.md.
    roboflow_api_key: str = ""
    roboflow_workspace_name: str = ""
    roboflow_workflow_id: str = ""
    roboflow_confidence_threshold: float = 0.5
```

In `.env.example`, replace lines 19–23:

```
# Roboflow hosted tongue detector
ROBOFLOW_API_KEY=
ROBOFLOW_MODEL_ID=
ROBOFLOW_CONFIDENCE_THRESHOLD=0.5
ROBOFLOW_CROP_PADDING_RATIO=0.12
```

with:

```
# Roboflow serverless workflow (tongue detect + server-side crop)
# See docs/adr/0004-serverless-workflow-crop.md for the console-side invariants.
ROBOFLOW_API_KEY=
ROBOFLOW_WORKSPACE_NAME=
ROBOFLOW_WORKFLOW_ID=tongue-detect-crop
ROBOFLOW_CONFIDENCE_THRESHOLD=0.5
```

- [ ] **Step 4: Rewrite the detector**

Replace the full contents of `app/vision/detector.py`:

```python
import asyncio
import io

from inference_sdk import InferenceHTTPClient
from PIL import Image
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.vision.crop import decode_crop

ROBOFLOW_SERVERLESS_API_URL = "https://serverless.roboflow.com"
WORKFLOW_TIMEOUT_SECONDS = 30


class TongueDetectionError(Exception):
    """The Roboflow workflow call failed: network, timeout, or a response
    that violates the contract in docs/adr/0004-serverless-workflow-crop.md.

    Distinct from a clean "no tongue" (detect_and_crop -> None): callers
    should reply with a system-hiccup message, never retake guidance.
    """


class CroppedTongue(BaseModel):
    """A tongue photo cropped server-side by the Roboflow workflow."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    image: Image.Image
    confidence: float


class TongueDetector:
    """Wraps the Roboflow serverless workflow (tongue-detect-crop), which
    detects the tongue, keeps the top-1 detection, and crops server-side.

    Console-side invariants (docs/adr/0004-serverless-workflow-crop.md):
    the workflow's model-node threshold must stay BELOW
    `roboflow_confidence_threshold` (the app-side gate is the only
    authoritative "tongue found?" decision -- docs/message-flow.md), and a
    top-1 detections filter keeps both output lists at <= 1 entry. The
    argmax pairing below is insurance against console edits breaking that.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = InferenceHTTPClient(
            api_url=ROBOFLOW_SERVERLESS_API_URL, api_key=settings.roboflow_api_key
        )

    async def detect_and_crop(self, image_bytes: bytes) -> CroppedTongue | None:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.run_workflow,
                    workspace_name=self._settings.roboflow_workspace_name,
                    workflow_id=self._settings.roboflow_workflow_id,
                    images={"image": image},
                    use_cache=False,
                ),
                timeout=WORKFLOW_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise TongueDetectionError("Roboflow workflow call timed out") from exc
        except Exception as exc:
            raise TongueDetectionError("Roboflow workflow call failed") from exc

        return self._parse_result(results)

    def _parse_result(self, results: object) -> CroppedTongue | None:
        try:
            entry = results[0]
            predictions = entry["raw_predictions"]["predictions"]
            crops = entry["output_tongue_crop"]

            if not predictions:
                return None
            if len(crops) != len(predictions):
                raise TongueDetectionError(
                    f"Workflow contract violation: {len(crops)} crops for "
                    f"{len(predictions)} predictions"
                )

            best_index = max(
                range(len(predictions)), key=lambda i: predictions[i]["confidence"]
            )
            best = predictions[best_index]
            if best["confidence"] < self._settings.roboflow_confidence_threshold:
                return None

            return CroppedTongue(
                image=decode_crop(crops[best_index]), confidence=best["confidence"]
            )
        except TongueDetectionError:
            raise
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise TongueDetectionError(f"Malformed workflow response: {exc!r}") from exc
```

(`ValueError` in that tuple converts `decode_crop` failures — see below — into
`TongueDetectionError` alongside the structural parse errors.)

Create `app/vision/crop.py` (focused helper, keeps the detector under one responsibility):

```python
import base64
import binascii
import io

from PIL import Image


def decode_crop(crop: dict) -> Image.Image:
    """Decode a Roboflow workflow crop output ({"type": "base64", "value": ...})
    into a PIL image. Raises ValueError on anything that is not a decodable
    image -- the detector wraps it into TongueDetectionError.
    """
    try:
        raw = base64.b64decode(crop["value"], validate=True)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except (KeyError, TypeError, binascii.Error, OSError) as exc:
        raise ValueError(f"Workflow crop did not decode to an image: {exc!r}") from exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/vision/test_detector.py -v`
Expected: 10 passed.

- [ ] **Step 6: Verify nothing else referenced the deleted config**

Run: `grep -rn "roboflow_model_id\|roboflow_crop_padding_ratio\|_crop_with_padding\|detect.roboflow.com" app/ tests/`
Expected: no matches.

Run: `uv run pytest && uv run ruff check app tests`
Expected: full suite passes, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add app/config.py app/vision/detector.py app/vision/crop.py .env.example tests/vision/
git commit -m "feat: migrate tongue detection to Roboflow serverless workflow"
```

---

### Task 2: Dispatcher guard — vision failures become a system-hiccup reply

**Files:**
- Modify: `app/pipeline/dispatcher.py` (imports, new constant, `handle_image_message`)
- Test: `tests/pipeline/test_dispatcher_images.py`

**Interfaces:**
- Consumes (from Task 1): `TongueDetectionError`, `CroppedTongue`, `TongueDetector.detect_and_crop(image_bytes) -> CroppedTongue | None` from `app.vision.detector`.
- Produces: module constant `SYSTEM_HICCUP_MESSAGE` in `app.pipeline.dispatcher` (Task 3's docs reference this behavior; tests import it).

- [ ] **Step 1: Write the failing tests**

Create `tests/pipeline/test_dispatcher_images.py`:

```python
import io
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/pipeline/test_dispatcher_images.py -v`
Expected: `test_no_tongue_still_sends_retake_guidance` and the happy-path test PASS (existing behavior); the two error tests FAIL with the raised exception propagating out of `handle_image_message` (`TongueDetectionError: roboflow down` / `RuntimeError: vision model outage`) — exactly the silent-death bug this task fixes.

- [ ] **Step 3: Add the guard to the dispatcher**

In `app/pipeline/dispatcher.py`:

Add to the imports (top of file):

```python
import logging
```

and change the detector import to also pull the error:

```python
from app.vision.detector import TongueDetectionError, TongueDetector
```

Add below the imports, next to the other module constants:

```python
logger = logging.getLogger(__name__)
```

Add after `RETAKE_GUIDANCE` (line 30):

```python
SYSTEM_HICCUP_MESSAGE = (
    "ขออภัยค่ะ ระบบวิเคราะห์ภาพขัดข้องชั่วคราว กรุณาลองส่งภาพอีกครั้งภายหลังนะคะ"
)
```

Replace the body of `handle_image_message` between `image_bytes = ...` and `turn_text = ...` (currently lines 59–70):

```python
    try:
        detector = TongueDetector(settings)
        cropped = await detector.detect_and_crop(image_bytes)

        description = None
        if cropped is not None:
            describer = VisionDescriber(settings)
            description = await describer.describe(cropped.image)
    except Exception:
        # Detector or describer outage must read as a system hiccup, never
        # as "your photo is bad" -- see docs/adr/0004-serverless-workflow-crop.md.
        # TongueDetectionError and describer/LLM errors share the same remedy.
        logger.exception("Vision pipeline failed for user %s", user_id)
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=SYSTEM_HICCUP_MESSAGE
        )
        return

    if cropped is None:
        # No tongue detected: guidance only, never a Tongue Assessment, and
        # not recorded in the working buffer -- see CONTEXT.md -> Tongue Assessment.
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=RETAKE_GUIDANCE
        )
        return
```

(The `turn_text = ...` block and everything after it stays exactly as-is; `description` is guaranteed non-None past the `cropped is None` return.)

Note: `TongueDetectionError` is imported for API clarity and future granular handling, but the guard intentionally catches `Exception` — the agreed design is one guard covering the detect→describe stretch with a single user remedy. If ruff flags the import as unused (F401), drop it from the import line rather than suppressing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/pipeline/ -v`
Expected: all pass, including the pre-existing `test_dispatcher_profile.py`.

- [ ] **Step 5: Full suite + lint**

Run: `uv run pytest && uv run ruff check app tests`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/dispatcher.py tests/pipeline/test_dispatcher_images.py
git commit -m "feat: guard vision pipeline failures with system-hiccup reply"
```

---

### Task 3: Documentation — ADR 0004 + message-flow note

**Files:**
- Create: `docs/adr/0004-serverless-workflow-crop.md`
- Modify: `docs/message-flow.md` (the `image` branch note, lines 77–81)

**Interfaces:**
- Consumes: the behavior shipped in Tasks 1–2 (response contract, three-outcome failure contract, `SYSTEM_HICCUP_MESSAGE` behavior).
- Produces: the ADR path `docs/adr/0004-serverless-workflow-crop.md` that code comments in Tasks 1–2 already reference.

- [ ] **Step 1: Write ADR 0004**

Create `docs/adr/0004-serverless-workflow-crop.md` (match the style of ADR 0001: title, context paragraph, Why, Consequences):

```markdown
# Tongue detection and crop move server-side into a Roboflow workflow

`TongueDetector` calls a Roboflow serverless **workflow** (`tongue-detect-crop` on `serverless.roboflow.com`) instead of the bare hosted-model endpoint. The workflow detects the tongue, keeps only the top-1 detection, crops server-side, and returns two outputs per image: `output_tongue_crop` (a base64 crop) and `raw_predictions` (bounding boxes with confidences). The app decodes the crop as the Vision Describer's input and applies its own confidence threshold to `raw_predictions` — the deterministic "Tongue found?" diamond in [message-flow](../message-flow.md) stays in app code, tunable via `ROBOFLOW_CONFIDENCE_THRESHOLD` without touching the workflow.

## Why

- One round-trip returns both the decision data and the describer input; the app no longer re-implements crop geometry (the old local `_crop_with_padding` and `ROBOFLOW_CROP_PADDING_RATIO` are gone).
- Crop logic lives next to the model that produces the boxes, so retraining and re-cropping evolve together in the Roboflow console.
- Keeping the threshold app-side keeps the documented decision boundary in the repo — versioned, testable, and visible in config.

## Console-side invariants

The repo cannot enforce these; they live in the Roboflow workflow definition and hold the contract together. Re-check both after **any** console edit:

1. **Top-1 filter** — a detections filter keeps at most one detection, so `output_tongue_crop` and `raw_predictions.predictions` each carry ≤ 1 entry. The app still pairs crop↔prediction by argmax confidence and raises on a length mismatch, as insurance.
2. **Threshold hierarchy** — the workflow's model-node confidence threshold (~0.25) must stay *below* `ROBOFLOW_CONFIDENCE_THRESHOLD` (default 0.5). If the console value climbs above the app value, the app-side gate silently becomes dead code.

## Failure contract

`detect_and_crop` distinguishes three outcomes: a `CroppedTongue`; a clean "no tongue" (`None` → Thai retake guidance, turn not recorded — unchanged); and `TongueDetectionError` for network, timeout (30 s), or contract violations. The dispatcher turns any detector/describer failure into a Thai "system hiccup, try again later" reply — an outage is never presented as a bad photo, which would send users into pointless retake loops.

## Consequences

- Editing the workflow in the Roboflow console can break production without any repo change — the invariants above are the checklist.
- The crop is exactly the detection bbox (no padding). If the Vision Describer proves to need context around the tongue, padding belongs in the workflow's crop node, not in app code.
- `use_cache=False` on every call: console edits take effect immediately, at the cost of re-fetching the workflow definition per request.
- Every tongue turn still costs one Roboflow round-trip plus one Describer call; the workflow adds no extra network hop over the old model endpoint.
```

- [ ] **Step 2: Update the message-flow image branch note**

In `docs/message-flow.md`, replace the `image` branch note (lines 77–81):

```markdown
**`image`** — tongue detection is a deterministic pipeline step that runs
*before* the agent ([ADR 0001](adr/0001-two-model-pipeline.md)): the
[Vision Describer](../CONTEXT.md) only describes; the Advisor makes the
[Tongue Assessment](../CONTEXT.md). No detected tongue → retake guidance,
never an Assessment, and the turn is not recorded.
```

with:

```markdown
**`image`** — tongue detection is a deterministic pipeline step that runs
*before* the agent ([ADR 0001](adr/0001-two-model-pipeline.md)): the
[Vision Describer](../CONTEXT.md) only describes; the Advisor makes the
[Tongue Assessment](../CONTEXT.md). Detection and crop run server-side in
a Roboflow workflow ([ADR 0004](adr/0004-serverless-workflow-crop.md));
the confidence gate stays in app code. No detected tongue → retake
guidance, never an Assessment, and the turn is not recorded. A detector
or describer *failure* (outage, timeout) instead sends a Thai
system-hiccup message — an outage is never presented as a bad photo.
```

- [ ] **Step 3: Verify doc links resolve**

Run: `ls docs/adr/0004-serverless-workflow-crop.md && grep -n "0004-serverless-workflow-crop" docs/message-flow.md app/vision/detector.py app/pipeline/dispatcher.py app/config.py`
Expected: file exists; the ADR is referenced from `message-flow.md` and from the code comments written in Tasks 1–2.

- [ ] **Step 4: Commit**

```bash
git add docs/adr/0004-serverless-workflow-crop.md docs/message-flow.md
git commit -m "docs: record serverless workflow crop decision (ADR 0004)"
```

---

## Post-plan manual steps (user, not automatable)

1. In the Roboflow console: rename the workflow to `tongue-detect-crop`, add the top-1 detections filter, set the model-node threshold to ~0.25, confirm output names `output_tongue_crop` and `raw_predictions`.
2. In the local `.env`: replace `ROBOFLOW_MODEL_ID` with `ROBOFLOW_WORKSPACE_NAME=arparwuts-workspace` and `ROBOFLOW_WORKFLOW_ID=tongue-detect-crop`; delete `ROBOFLOW_CROP_PADDING_RATIO`.
3. Send a real tongue photo through LINE against a running instance to verify the end-to-end path (detection → crop → description → assessment), plus a non-tongue photo (retake guidance).
