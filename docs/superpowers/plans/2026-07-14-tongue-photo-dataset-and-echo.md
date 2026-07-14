# Tongue Photo Dataset & Echo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ADR 0007 (`docs/adr/0007-tongue-photo-dataset-and-echo.md`): persist every Roboflow tongue crop in a new `tongue_photos` Mongo collection, and echo gate-passed crops back to the user as a LINE `ImageMessage` served from a new unauthenticated `GET /tongue-photos/{photo_id}` endpoint.

**Architecture:** A standalone `app/tongue_photos/` package (repository + FastAPI router) deliberately outside the memory architecture. The `TongueDetector` contract widens so below-gate crops are returned (with `passed_gate=False`) instead of `None`. The dispatcher saves the crop the moment detection succeeds, patches the description in later, and passes an `image_url` to `LineMessenger.reply_or_push`, which grows a four-rung degrade chain.

**Tech Stack:** Python 3.11, FastAPI, motor (Mongo), pydantic, line-bot-sdk v3, Pillow. Tests: pytest (asyncio_mode=auto), mongomock-motor, httpx ASGITransport. Run everything with `uv run`.

## Global Constraints

- Collection name: `tongue_photos`. Endpoint path: `GET /tongue-photos/{photo_id}`. Config field: `public_base_url` (env `PUBLIC_BASE_URL`), default `""`.
- `photo_id` is a **UUID4 string, never a Mongo ObjectId** (ObjectIds are enumerable — ADR 0007).
- Image bytes are stored as **BSON Binary, never base64**. Passing Python `bytes` to pymongo/motor stores BSON Binary subtype 0 automatically — do not wrap or encode.
- **No listing/enumeration endpoints or repository methods.** Possession of the UUID is the authorization.
- Failure contract (ADR 0007): the image must never cost the user their Assessment. Degrade one rung at a time: reply `[text, image+topics]` → push `[text, image+topics]` → push `[text+topics]` → push `[text]`. Mongo save failures are logged, never surfaced.
- Below-gate crops (`passed_gate=False`) are saved but **never described, never assessed, never echoed** — the retake flow is unchanged.
- All pydantic models are `ConfigDict(frozen=True)`, matching `app/models/schemas.py`.
- Ruff: line length 100, rules E/F/I/UP/B. Run `uv run ruff check .` before each commit.
- Tests are async by default (`asyncio_mode = "auto"` in pyproject) — no `@pytest.mark.asyncio` needed.
- Commit messages: `<type>: <description>` (feat/fix/test/docs/refactor). No AI attribution lines.
- Work on a feature branch, e.g. `feat/tongue-photos`, created from `main` before Task 1.

---

### Task 1: Widen the TongueDetector contract (`passed_gate`)

Below-threshold crops must become distinguishable from "nothing detected" (ADR 0007 consequence). `CroppedTongue` gains a required `passed_gate: bool`; `detect_and_crop` returns the crop even below the gate. The dispatcher's gate check moves from "crop is None" to "crop is None **or** failed the gate" **in the same task** — otherwise below-gate photos would suddenly get described and assessed.

**Files:**
- Modify: `app/vision/detector.py:24-31` (CroppedTongue), `app/vision/detector.py:85-94` (`_parse_result` tail)
- Modify: `app/pipeline/dispatcher.py:95-101` (retake branch)
- Test: `tests/vision/test_detector.py`, `tests/pipeline/test_dispatcher_images.py`

**Interfaces:**
- Consumes: existing `TongueDetector.detect_and_crop(image_bytes: bytes) -> CroppedTongue | None`
- Produces: `CroppedTongue(image: Image.Image, confidence: float, passed_gate: bool)` — frozen pydantic model, `passed_gate` **required** (no default). `detect_and_crop` returns `None` only when the workflow found no tongue at all; a below-threshold detection returns a `CroppedTongue` with `passed_gate=False`. Later tasks rely on exactly this.

- [ ] **Step 1: Write the failing detector tests**

In `tests/vision/test_detector.py`, replace `test_returns_none_when_best_confidence_below_threshold` (line 98-101) with:

```python
async def test_below_threshold_crop_is_returned_with_passed_gate_false():
    # ADR 0007: the crop is kept for threshold-calibration analysis; the
    # caller (dispatcher) is responsible for treating it like a retake.
    detector, _ = _detector_returning(_response([_prediction(0.3)], [_crop()]))

    result = await detector.detect_and_crop(_jpeg_bytes())

    assert isinstance(result, CroppedTongue)
    assert result.passed_gate is False
    assert result.confidence == 0.3
```

And in `test_returns_cropped_tongue_with_confidence_on_detection` (line 79), add one assertion after `assert result.confidence == 0.92`:

```python
    assert result.passed_gate is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/vision/test_detector.py -v`
Expected: FAIL — `test_below_threshold_...` gets `None` instead of `CroppedTongue`; the happy-path test fails with `AttributeError`/validation error on `passed_gate`.

- [ ] **Step 3: Implement the detector change**

In `app/vision/detector.py`, replace the `CroppedTongue` class (lines 24-31) with:

```python
class CroppedTongue(BaseModel):
    """A tongue photo cropped server-side by the Roboflow workflow.

    passed_gate: whether confidence cleared the app-side threshold. Below-
    gate crops are still returned for dataset capture (ADR 0007); callers
    must treat passed_gate=False like "no tongue" in the user-facing flow.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    image: Image.Image
    confidence: float
    passed_gate: bool
```

In `_parse_result`, replace the threshold check and return (lines 88-94):

```python
            best = predictions[best_index]
            return CroppedTongue(
                image=decode_crop(crops[best_index]),
                confidence=best["confidence"],
                passed_gate=best["confidence"]
                >= self._settings.roboflow_confidence_threshold,
            )
```

(The `if best["confidence"] < ...: return None` lines are deleted.)

- [ ] **Step 4: Update the dispatcher gate check and its tests**

In `app/pipeline/dispatcher.py`, replace the retake branch (lines 95-101) with:

```python
    if cropped is None or not cropped.passed_gate:
        # No tongue, or detected but below the confidence gate: guidance
        # only, never a Tongue Assessment, and not recorded in the working
        # buffer -- see CONTEXT.md -> Tongue Assessment and ADR 0007.
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=RETAKE_GUIDANCE
        )
        return
```

In `tests/pipeline/test_dispatcher_images.py`, every `CroppedTongue(image=_pil_image(), confidence=0.9)` (three occurrences: lines 97, 147, 167) becomes:

```python
CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)
```

Then add a new test after `test_no_tongue_still_sends_retake_guidance`:

```python
async def test_below_gate_crop_sends_retake_and_never_describes(monkeypatch):
    # ADR 0007: rejected crops are never described, assessed, or echoed --
    # the user-facing retake flow is unchanged.
    messenger, consultation_inputs = _patch_common(monkeypatch)

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
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/vision tests/pipeline -v`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check .
git add app/vision/detector.py app/pipeline/dispatcher.py tests/vision/test_detector.py tests/pipeline/test_dispatcher_images.py
git commit -m "feat: distinguish below-gate tongue crops from no detection"
```

---

### Task 2: TonguePhoto model, JPEG helper, and repository

**Files:**
- Modify: `app/models/schemas.py` (add `TonguePhoto` after `TongueDescription`)
- Modify: `app/vision/crop.py` (add `encode_jpeg`)
- Modify: `app/vision/describer.py:34-36` (reuse `encode_jpeg` — DRY)
- Create: `app/tongue_photos/__init__.py` (empty), `app/tongue_photos/repository.py`
- Test: `tests/tongue_photos/__init__.py` (empty), `tests/tongue_photos/test_repository.py`

**Interfaces:**
- Consumes: `TongueDescription` from `app/models/schemas.py`; `_utc_when_naive` validator helper in the same file; `mongomock_motor.AsyncMongoMockClient` in tests.
- Produces (later tasks rely on these exact names):
  - `TonguePhoto(photo_id: str, user_id: str, image: bytes, captured_at: datetime, confidence: float, passed_gate: bool, line_message_id: str, description: TongueDescription | None = None)` — frozen.
  - `encode_jpeg(image: Image.Image) -> bytes` in `app/vision/crop.py`.
  - `TonguePhotoRepository(db)` with `async insert(photo: TonguePhoto) -> None`, `async set_description(photo_id: str, description: TongueDescription) -> None`, `async get_jpeg(photo_id: str) -> bytes | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tongue_photos/__init__.py` (empty) and `tests/tongue_photos/test_repository.py`:

```python
from datetime import UTC, datetime

from mongomock_motor import AsyncMongoMockClient

from app.models.schemas import TongueDescription, TonguePhoto
from app.tongue_photos.repository import TonguePhotoRepository

NOW = datetime.now(UTC).replace(microsecond=0)
JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _repo() -> tuple[TonguePhotoRepository, object]:
    db = AsyncMongoMockClient()["test_db"]
    return TonguePhotoRepository(db), db


def _photo(**overrides) -> TonguePhoto:
    fields: dict = dict(
        photo_id="11111111-1111-4111-8111-111111111111",
        user_id="U1",
        image=JPEG,
        captured_at=NOW,
        confidence=0.9,
        passed_gate=True,
        line_message_id="M1",
    )
    fields.update(overrides)
    return TonguePhoto(**fields)


def _description() -> TongueDescription:
    return TongueDescription(
        body_color="แดง",
        body_shape="ปกติ",
        coating_color="ขาว",
        coating_thickness="บาง",
        moisture="ชุ่มชื้น",
        cracks=False,
        teeth_marks=False,
        quality="clear",
    )


async def test_insert_then_get_jpeg_round_trips_the_bytes():
    repo, _ = _repo()
    await repo.insert(_photo())

    assert await repo.get_jpeg("11111111-1111-4111-8111-111111111111") == JPEG


async def test_get_jpeg_returns_none_for_unknown_photo_id():
    repo, _ = _repo()

    assert await repo.get_jpeg("22222222-2222-4222-8222-222222222222") is None


async def test_insert_stores_description_as_null():
    # Insert-after-detect, update-after-describe (ADR 0007): a null
    # description marks exactly which stage failed.
    repo, db = _repo()
    await repo.insert(_photo())

    doc = await db["tongue_photos"].find_one({"photo_id": _photo().photo_id})
    assert doc["description"] is None
    assert doc["passed_gate"] is True
    assert doc["confidence"] == 0.9
    assert doc["line_message_id"] == "M1"


async def test_set_description_patches_the_document():
    repo, db = _repo()
    await repo.insert(_photo())

    await repo.set_description(_photo().photo_id, _description())

    doc = await db["tongue_photos"].find_one({"photo_id": _photo().photo_id})
    assert doc["description"]["body_color"] == "แดง"
    assert bytes(doc["image"]) == JPEG  # image untouched by the patch


async def test_below_gate_crop_is_stored_with_passed_gate_false():
    repo, db = _repo()
    await repo.insert(_photo(passed_gate=False, confidence=0.3))

    doc = await db["tongue_photos"].find_one({"photo_id": _photo().photo_id})
    assert doc["passed_gate"] is False
```

Also append the `encode_jpeg` test to the same file, `tests/tongue_photos/test_repository.py`:

```python
def test_encode_jpeg_produces_decodable_jpeg_bytes():
    from io import BytesIO

    from PIL import Image

    from app.vision.crop import encode_jpeg

    image = Image.new("RGB", (16, 16), (200, 60, 60))

    raw = encode_jpeg(image)

    round_tripped = Image.open(BytesIO(raw))
    assert round_tripped.format == "JPEG"
    assert round_tripped.size == (16, 16)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tongue_photos -v`
Expected: FAIL with `ImportError` (`TonguePhoto`, `app.tongue_photos.repository`, `encode_jpeg` don't exist).

- [ ] **Step 3: Implement**

In `app/models/schemas.py`, after `TongueDescription` (line 48), add:

```python
class TonguePhoto(BaseModel):
    """One Roboflow crop persisted for the thesis dataset (ADR 0007).

    Deliberately outside the memory architecture: survives Consultation
    close and gate-failed discards. `image` is raw JPEG bytes (stored as
    BSON Binary, never base64). `description` stays None until the Vision
    Describer returns -- a null description marks a describer-stage failure.
    """

    model_config = ConfigDict(frozen=True)

    photo_id: str
    user_id: str
    image: bytes
    captured_at: datetime
    confidence: float
    passed_gate: bool
    line_message_id: str
    description: TongueDescription | None = None

    @field_validator("captured_at")
    @classmethod
    def _assume_utc_when_naive(cls, value: datetime) -> datetime:
        return _utc_when_naive(value)
```

In `app/vision/crop.py`, append:

```python
def encode_jpeg(image: Image.Image) -> bytes:
    """Encode a PIL image as JPEG bytes -- the single encode step for both
    Tongue Photo storage (ADR 0007) and the describer's data URL."""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()
```

Create `app/tongue_photos/__init__.py` (empty) and `app/tongue_photos/repository.py`:

```python
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.schemas import TongueDescription, TonguePhoto

COLLECTION = "tongue_photos"


class TonguePhotoRepository:
    """Standalone thesis-dataset store (docs/adr/0007-tongue-photo-dataset-and-echo.md),
    deliberately outside the memory architecture: documents survive
    Consultation close and gate-failed discards.

    Insert-after-detect, patch-after-describe. Deliberately NO listing or
    enumeration methods: the capability URL (UUID4 photo_id) is the only
    read path, and possession of the UUID is the authorization.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db[COLLECTION]

    async def insert(self, photo: TonguePhoto) -> None:
        # model_dump keeps `image` as bytes; pymongo stores bytes as BSON
        # Binary subtype 0 -- no base64, no explicit Binary wrapper needed.
        await self._collection.insert_one(photo.model_dump())

    async def set_description(self, photo_id: str, description: TongueDescription) -> None:
        await self._collection.update_one(
            {"photo_id": photo_id}, {"$set": {"description": description.model_dump()}}
        )

    async def get_jpeg(self, photo_id: str) -> bytes | None:
        doc = await self._collection.find_one({"photo_id": photo_id}, {"image": 1})
        return bytes(doc["image"]) if doc else None
```

In `app/vision/describer.py`, replace lines 34-36:

```python
        encoded = base64.standard_b64encode(encode_jpeg(image)).decode("utf-8")
```

with the import `from app.vision.crop import encode_jpeg` added at the top, and delete the now-unused `buffer = io.BytesIO()` / `image.save(...)` lines and the `import io` if nothing else uses it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tongue_photos tests/vision tests/models -v`
Expected: all PASS (including the untouched describer-adjacent tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add app/models/schemas.py app/vision/crop.py app/vision/describer.py app/tongue_photos tests/tongue_photos
git commit -m "feat: add TonguePhoto model and tongue_photos repository"
```

---

### Task 3: Serving endpoint `GET /tongue-photos/{photo_id}`

**Files:**
- Create: `app/tongue_photos/router.py`
- Modify: `app/main.py`
- Test: `tests/tongue_photos/test_router.py`

**Interfaces:**
- Consumes: `TonguePhotoRepository.get_jpeg` (Task 2); `get_database` from `app/memory/db.py`.
- Produces: `router` (APIRouter) exposing `GET /tongue-photos/{photo_id}` → `200 image/jpeg` or `404`. Registered on the app in `app/main.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tongue_photos/test_router.py`:

```python
"""Tests for the capability-URL serving endpoint (ADR 0007).

Unauthenticated by design: LINE's fetchers and the user's client GET the
JPEG without credentials; possession of the UUID4 is the authorization.
"""

from datetime import UTC, datetime

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

import app.tongue_photos.router as tp_router
from app.main import app
from app.models.schemas import TonguePhoto
from app.tongue_photos.repository import TonguePhotoRepository

PHOTO_ID = "11111111-1111-4111-8111-111111111111"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


@pytest.fixture
def mock_db(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(tp_router, "get_database", lambda: db)
    return db


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def _seed(db) -> None:
    photo = TonguePhoto(
        photo_id=PHOTO_ID,
        user_id="U1",
        image=JPEG,
        captured_at=datetime.now(UTC),
        confidence=0.9,
        passed_gate=True,
        line_message_id="M1",
    )
    await TonguePhotoRepository(db).insert(photo)


async def test_serves_stored_jpeg_with_image_content_type(mock_db):
    await _seed(mock_db)

    response = await _get(f"/tongue-photos/{PHOTO_ID}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == JPEG


async def test_unknown_photo_id_returns_404(mock_db):
    response = await _get("/tongue-photos/99999999-9999-4999-8999-999999999999")

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tongue_photos/test_router.py -v`
Expected: FAIL with `ModuleNotFoundError: app.tongue_photos.router`.

- [ ] **Step 3: Implement the router and register it**

Create `app/tongue_photos/router.py`:

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.memory.db import get_database
from app.tongue_photos.repository import TonguePhotoRepository

router = APIRouter()


@router.get("/tongue-photos/{photo_id}")
async def get_tongue_photo(photo_id: str) -> Response:
    """Unauthenticated read-only capability URL (ADR 0007).

    LINE's servers fetch ImageMessage URLs without credentials, so this
    endpoint carries none; possession of the UUID4 is the authorization.
    Do NOT add listing/enumeration endpoints.
    """
    jpeg = await TonguePhotoRepository(get_database()).get_jpeg(photo_id)
    if jpeg is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=jpeg, media_type="image/jpeg")
```

In `app/main.py`, register it:

```python
from fastapi import FastAPI

from app.line.router import router as line_router
from app.tongue_photos.router import router as tongue_photos_router

app = FastAPI(title="TTM Consultation Assistant")
app.include_router(line_router)
app.include_router(tongue_photos_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tongue_photos tests/line -v`
Expected: all PASS (webhook tests confirm the new router didn't disturb the app).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add app/tongue_photos/router.py app/main.py tests/tongue_photos/test_router.py
git commit -m "feat: serve tongue photos via capability URL endpoint"
```

---

### Task 4: LineMessenger image support and the four-rung degrade chain

**Files:**
- Modify: `app/line/messaging.py`
- Test: `tests/line/test_messaging.py`

**Interfaces:**
- Consumes: `ImageMessage` from `linebot.v3.messaging` (same SDK module as `TextMessage`).
- Produces (Task 5 relies on these):
  - `build_image_message(image_url: str, topics: Sequence[str] = ()) -> ImageMessage` — same URL in both `originalContentUrl` and `previewImageUrl`, topics as its Quick Reply.
  - `LineMessenger.reply(reply_token, text, topics=(), image_url=None)`, `.push(user_id, text, topics=(), image_url=None)` — with `image_url`, the payload is `[TextMessage(text), ImageMessage(url, quickReply=topics)]`; without, the existing single `TextMessage(text, topics)`.
  - `LineMessenger.reply_or_push(*, reply_token, user_id, text, topics=(), image_url=None)` — degrade chain per ADR 0007.

- [ ] **Step 1: Write the failing tests**

**First**, update the four existing fakes in `tests/line/test_messaging.py` — `reply_or_push` will now pass `image_url` through, and a fake that rejects the argument would masquerade as a LINE failure and silently take the wrong branch. Every `async def fake_reply(reply_token, text, topics=())`, `failing_reply(...)`, `fake_push(user_id, text, topics=())`, `flaky_push(...)`, `failing_push(...)` gains a trailing `image_url=None` parameter (bodies unchanged).

Then append these tests:

```python
from app.line.messaging import build_image_message


def test_build_image_message_uses_same_url_for_content_and_preview():
    # One JPEG serves both slots -- crops sit under LINE's 1 MB preview cap.
    message = build_image_message("https://example.com/tongue-photos/abc")
    assert message.original_content_url == "https://example.com/tongue-photos/abc"
    assert message.preview_image_url == "https://example.com/tongue-photos/abc"
    assert message.quick_reply is None


def test_build_image_message_carries_topics_as_quick_reply():
    # Quick Reply renders only under the LAST message in a reply, so the
    # Topic Menu rides on the image (ADR 0007).
    message = build_image_message("https://example.com/p/abc", ("หัวข้อหนึ่ง",))
    assert [i.action.label for i in message.quick_reply.items] == ["หัวข้อหนึ่ง"]


async def test_reply_with_image_sends_text_then_image_with_topics_on_image(monkeypatch):
    import app.line.messaging as messaging

    messenger = LineMessenger(_settings())
    sent_batches = []

    class _FakeApi:
        def __init__(self, client) -> None:
            pass

        async def reply_message(self, request):
            sent_batches.append(request.messages)

    class _FakeClient:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(messaging, "AsyncMessagingApi", _FakeApi)
    monkeypatch.setattr(LineMessenger, "_client", lambda self: _FakeClient())

    await messenger.reply(
        "R1", "คำตอบ", ("หัวข้อหนึ่ง",), image_url="https://example.com/p/abc"
    )

    (messages,) = sent_batches
    assert len(messages) == 2
    assert messages[0].text == "คำตอบ"
    assert messages[0].quick_reply is None  # topics moved to the image
    assert messages[1].original_content_url == "https://example.com/p/abc"
    assert [i.action.label for i in messages[1].quick_reply.items] == ["หัวข้อหนึ่ง"]


async def test_reply_or_push_degrades_image_to_text_topics_then_plain_text():
    # ADR 0007 chain: reply [text, image+topics] -> push [text, image+topics]
    # -> push [text+topics] -> push [text].
    messenger = LineMessenger(_settings())
    calls = []

    async def failing_reply(reply_token, text, topics=(), image_url=None):
        raise RuntimeError("reply token expired")

    async def flaky_push(user_id, text, topics=(), image_url=None):
        calls.append((text, tuple(topics), image_url))
        if image_url is not None or topics:
            raise RuntimeError("LINE rejected the payload")

    messenger.reply = failing_reply
    messenger.push = flaky_push

    await messenger.reply_or_push(
        reply_token="R1",
        user_id="U1",
        text="คำตอบ",
        topics=("หัวข้อหนึ่ง",),
        image_url="https://example.com/p/abc",
    )

    assert calls == [
        ("คำตอบ", ("หัวข้อหนึ่ง",), "https://example.com/p/abc"),
        ("คำตอบ", ("หัวข้อหนึ่ง",), None),
        ("คำตอบ", (), None),
    ]


async def test_reply_or_push_image_success_stops_the_chain():
    messenger = LineMessenger(_settings())
    calls = []

    async def ok_reply(reply_token, text, topics=(), image_url=None):
        calls.append((reply_token, text, tuple(topics), image_url))

    messenger.reply = ok_reply

    await messenger.reply_or_push(
        reply_token="R1",
        user_id="U1",
        text="คำตอบ",
        topics=("หัวข้อหนึ่ง",),
        image_url="https://example.com/p/abc",
    )

    assert calls == [("R1", "คำตอบ", ("หัวข้อหนึ่ง",), "https://example.com/p/abc")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/line/test_messaging.py -v`
Expected: new tests FAIL (`build_image_message` import error first); the pre-existing tests still pass.

- [ ] **Step 3: Implement**

In `app/line/messaging.py`, add `ImageMessage` to the `linebot.v3.messaging` import list, then replace `build_text_message` and add the helpers:

```python
def _quick_reply(topics: Sequence[str]) -> QuickReply | None:
    if not topics:
        return None
    return QuickReply(
        items=[QuickReplyItem(action=MessageAction(label=topic, text=topic)) for topic in topics]
    )


def build_text_message(text: str, topics: Sequence[str] = ()) -> TextMessage:
    """Render a reply with its Topic Menu as LINE Quick Reply buttons.

    Topics must already be capped (ADR 0006, enforced by
    app/advisor/topic_menu.py: at most 5 topics of <= 20 chars -- LINE
    rejects longer labels at the API, not in the SDK). Tapping a button
    sends its text as the user's next message.
    """
    return TextMessage(text=text, quickReply=_quick_reply(topics))


def build_image_message(image_url: str, topics: Sequence[str] = ()) -> ImageMessage:
    """A LINE ImageMessage is two public HTTPS URLs LINE's servers fetch --
    bytes cannot be pushed (ADR 0007). One JPEG serves both slots (crops sit
    under LINE's 1 MB preview cap). Topics ride here because Quick Reply
    renders only under the LAST message in a reply.
    """
    return ImageMessage(
        originalContentUrl=image_url,
        previewImageUrl=image_url,
        quickReply=_quick_reply(topics),
    )


def _build_messages(text: str, topics: Sequence[str], image_url: str | None) -> list:
    if image_url is None:
        return [build_text_message(text, topics)]
    return [build_text_message(text), build_image_message(image_url, topics)]
```

Replace `reply`, `push`, and `reply_or_push` in `LineMessenger`:

```python
    async def reply(
        self,
        reply_token: str,
        text: str,
        topics: Sequence[str] = (),
        image_url: str | None = None,
    ) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token, messages=_build_messages(text, topics, image_url)
                )
            )

    async def push(
        self,
        user_id: str,
        text: str,
        topics: Sequence[str] = (),
        image_url: str | None = None,
    ) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.push_message(
                PushMessageRequest(to=user_id, messages=_build_messages(text, topics, image_url))
            )

    async def reply_or_push(
        self,
        *,
        reply_token: str,
        user_id: str,
        text: str,
        topics: Sequence[str] = (),
        image_url: str | None = None,
    ) -> None:
        """Attempt the reply token; degrade one rung at a time (ADR 0007):
        reply [text, image+topics] -> push [text, image+topics] ->
        push [text+topics] -> push [text]. The image (then the Quick Reply)
        is shed before the text is ever at risk -- the same degrade-to-text
        philosophy as ADR 0006.
        """
        try:
            await self.reply(reply_token, text, topics, image_url)
            return
        except Exception:
            logger.warning("LINE reply failed for user %s; falling back to push", user_id)
        try:
            await self.push(user_id, text, topics, image_url)
            return
        except Exception:
            if image_url is None and not topics:
                raise
            logger.warning(
                "LINE push failed for user %s; degrading payload", user_id, exc_info=True
            )
        if image_url is not None:
            try:
                await self.push(user_id, text, topics)
                return
            except Exception:
                if not topics:
                    raise
                logger.warning(
                    "LINE push without image failed for user %s; retrying as plain text",
                    user_id,
                    exc_info=True,
                )
        await self.push(user_id, text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/line -v`
Expected: all PASS, including all pre-existing degrade tests (the no-image chain must behave exactly as before).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add app/line/messaging.py tests/line/test_messaging.py
git commit -m "feat: echo images with a reply degrade chain in LineMessenger"
```

---

### Task 5: Dispatcher wiring — save, patch, echo, retention disclosure

**Files:**
- Modify: `app/config.py` (add `public_base_url`)
- Modify: `app/pipeline/dispatcher.py`
- Test: `tests/pipeline/test_dispatcher_images.py`, create `tests/pipeline/test_dispatcher_follow.py`

**Interfaces:**
- Consumes: `CroppedTongue.passed_gate` (Task 1); `TonguePhoto`, `TonguePhotoRepository`, `encode_jpeg` (Task 2); `reply_or_push(..., image_url=)` (Task 4).
- Produces: `Settings.public_base_url: str = ""` (env `PUBLIC_BASE_URL`). Dispatcher helpers `_save_tongue_photo`, `_save_description`, `_photo_url` (module-private; tests reach them via the module).

- [ ] **Step 1: Write the failing tests**

In `tests/pipeline/test_dispatcher_images.py`:

1. `_settings()` gains an optional override: 

```python
def _settings(**overrides) -> Settings:
    return Settings(
        line_channel_secret="test", line_channel_access_token="test", **overrides
    )
```

2. `_FakeMessenger.reply_or_push` gains image capture:

```python
    async def reply_or_push(self, *, reply_token, user_id, text, topics=(), image_url=None) -> None:
        self.sent.append(text)
        self.images.append(image_url)
```

with `self.images: list = []` added in `__init__`.

3. `_patch_common` additionally stubs the photo store and returns the recorders:

```python
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
```

Every existing `messenger, consultation_inputs = _patch_common(monkeypatch)` becomes `messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)` (unused names are fine).

4. New tests:

```python
async def test_gate_passed_crop_is_saved_then_description_patched(monkeypatch):
    # Insert after detect, update after describe (ADR 0007).
    messenger, consultation_inputs, saved, patched = _patch_common(monkeypatch)

    async def ok_detect(self, image_bytes):
        return CroppedTongue(image=_pil_image(), confidence=0.9, passed_gate=True)

    async def ok_describe(self, image):
        return _FakeDescription()

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
        return _FakeDescription()

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
        return _FakeDescription()

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
        return _FakeDescription()

    monkeypatch.setattr(_StubDetector, "detect_and_crop", ok_detect, raising=False)
    monkeypatch.setattr(dispatcher, "TongueDetector", _StubDetector)
    monkeypatch.setattr(_StubDescriber, "describe", ok_describe, raising=False)
    monkeypatch.setattr(dispatcher, "VisionDescriber", _StubDescriber)

    await dispatcher.handle_image_message(_event(), _settings())  # default ""

    assert len(saved) == 1  # dataset capture is independent of the echo
    assert messenger.sent == ["คำแนะนำจากผู้ช่วย"]
    assert messenger.images == [None]
```

Create `tests/pipeline/test_dispatcher_follow.py`:

```python
import app.pipeline.dispatcher as dispatcher


def test_welcome_message_discloses_photo_retention():
    # ADR 0007: indefinite retention is disclosed by one sentence in the
    # follow welcome message.
    assert "วิจัย" in dispatcher.WELCOME_MESSAGE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/pipeline -v`
Expected: new tests FAIL (`saved` stays empty, `messenger.images` missing URL, welcome sentence absent); updated existing tests PASS.

- [ ] **Step 3: Implement**

In `app/config.py`, after the Roboflow block (line 47), add:

```python
    # Public HTTPS origin of this app (the tunnel hostname), used to build
    # tongue-photo capability URLs (ADR 0007). Empty disables the image echo;
    # changing it breaks images already delivered to chats (URLs are frozen
    # in LINE's message history).
    public_base_url: str = ""
```

In `app/pipeline/dispatcher.py`:

1. Add imports: `import uuid` (stdlib block), and

```python
from app.models.schemas import ConsultationTurn, TongueDescription, TonguePhoto
from app.tongue_photos.repository import TonguePhotoRepository
from app.vision.crop import encode_jpeg
from app.vision.detector import CroppedTongue, TongueDetector
```

2. Extend `WELCOME_MESSAGE`:

```python
WELCOME_MESSAGE = (
    "สวัสดีค่ะ ดิฉันเป็นผู้ช่วยให้คำแนะนำด้านแพทย์แผนไทยเบื้องต้น "
    "ไม่ใช่แพทย์และไม่ได้ให้การวินิจฉัยทางการแพทย์ หากมีอาการรุนแรงหรือฉุกเฉิน "
    "กรุณาพบแพทย์หรือโทร 1669 ทันที "
    "ทั้งนี้ ภาพลิ้นที่ส่งเข้ามาเพื่อรับการประเมินจะถูกจัดเก็บไว้เพื่อการวิจัยค่ะ"
)
```

3. Add module-private helpers (after `handle_image_message`):

```python
async def _save_tongue_photo(
    cropped: CroppedTongue, message_id: str, user_id: str, settings: Settings
) -> str | None:
    """Persist the crop the moment detection succeeds (ADR 0007): dataset
    capture is independent of the gate, the describer, and the echo. Returns
    the photo_id, or None when the save failed -- a Mongo write error is
    logged, never surfaced, and the caller skips the echo so LINE is never
    handed a URL that would 404.
    """
    photo = TonguePhoto(
        # Capability URL id: UUID4, never a Mongo ObjectId (enumerable).
        photo_id=str(uuid.uuid4()),
        user_id=user_id,
        image=encode_jpeg(cropped.image),
        captured_at=datetime.now(UTC),
        confidence=cropped.confidence,
        passed_gate=cropped.passed_gate,
        line_message_id=message_id,
    )
    try:
        await TonguePhotoRepository(get_database(settings)).insert(photo)
    except Exception:
        logger.exception("Tongue Photo save failed for user %s", user_id)
        return None
    return photo.photo_id


async def _save_description(
    photo_id: str | None, description: TongueDescription, settings: Settings
) -> None:
    """Patch the Tongue Description into an already-saved photo. Best-effort
    for the same reason as _save_tongue_photo: never costs the user a turn."""
    if photo_id is None:
        return
    try:
        await TonguePhotoRepository(get_database(settings)).set_description(
            photo_id, description
        )
    except Exception:
        logger.exception("Tongue Description patch failed for photo %s", photo_id)


def _photo_url(photo_id: str | None, settings: Settings) -> str | None:
    if photo_id is None or not settings.public_base_url:
        return None
    return f"{settings.public_base_url.rstrip('/')}/tongue-photos/{photo_id}"
```

4. Rewrite `handle_image_message` (the download/detect `try` keeps the hiccup contract; describe moves to its own `try` so the save sits between them):

```python
async def handle_image_message(event: MessageEvent, settings: Settings) -> None:
    user_id = event.source.user_id
    messenger = LineMessenger(settings)
    try:
        await messenger.show_loading(user_id)
    except Exception:
        # The loading animation is cosmetic -- its failure must not cost the
        # user their Tongue Assessment.
        logger.warning("Loading animation failed for user %s", user_id, exc_info=True)

    try:
        image_bytes = await messenger.download_content(event.message.id)
        detector = TongueDetector(settings)
        cropped = await detector.detect_and_crop(image_bytes)
    except Exception:
        # Content download or detector outage must read as a system hiccup,
        # never as "your photo is bad" -- see
        # docs/adr/0004-serverless-workflow-crop.md.
        logger.exception("Vision pipeline failed for user %s", user_id)
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=SYSTEM_HICCUP_MESSAGE
        )
        return

    photo_id = None
    if cropped is not None:
        photo_id = await _save_tongue_photo(cropped, event.message.id, user_id, settings)

    if cropped is None or not cropped.passed_gate:
        # No tongue, or detected but below the confidence gate: guidance
        # only, never a Tongue Assessment (and below-gate crops are never
        # described or echoed -- ADR 0007), not recorded in the buffer.
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=RETAKE_GUIDANCE
        )
        return

    try:
        describer = VisionDescriber(settings)
        description = await describer.describe(cropped.image)
    except Exception:
        # Describer outage: same hiccup remedy, but the photo is already on
        # record with description null, marking exactly which stage failed.
        logger.exception("Vision describer failed for user %s", user_id)
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=SYSTEM_HICCUP_MESSAGE
        )
        return

    await _save_description(photo_id, description, settings)

    turn_text = (
        "[User sent a tongue photo.] Vision Describer observations: "
        f"{description.model_dump_json()}. Please give a TTM Tongue Assessment "
        "based on these observations."
    )

    async with user_queue.lock_for(user_id):
        parsed = await _run_consultation_turn(user_id, turn_text, settings)

    await messenger.reply_or_push(
        reply_token=event.reply_token,
        user_id=user_id,
        text=parsed.visible_text,
        topics=parsed.topics,
        image_url=_photo_url(photo_id, settings),
    )
```

Note for the implementer: `_save_description` calls `description.model_dump_json` nowhere — the fake `_FakeDescription` in tests only needs `model_dump_json` for the turn text; the repository stub records the object without dumping it. No test change needed beyond Step 1.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add app/config.py app/pipeline/dispatcher.py tests/pipeline/test_dispatcher_images.py tests/pipeline/test_dispatcher_follow.py
git commit -m "feat: persist tongue photos and echo them with the assessment"
```

---

### Task 6: Documentation and deployment note

**Files:**
- Modify: `docs/message-flow.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the mermaid diagram's image lane**

In `docs/message-flow.md`, replace the image-branch lines (lines 18-26) with:

```
    EVT -->|image| LOAD["Show loading indicator"]
    LOAD --> DL["Download image bytes"]
    DL --> DET["TongueDetector: detect + crop"]
    DET --> TF{"Tongue found?"}
    TF -->|no| RETAKE["Thai retake guidance<br/>turn not recorded"]
    RETAKE --> END2([End])
    TF -->|crop returned| SAVE["Persist Tongue Photo<br/>(ADR 0007, gate-independent)"]
    SAVE --> PG{"Passed confidence gate?"}
    PG -->|no| RETAKE
    PG -->|yes| VD["VisionDescriber &rarr; Tongue Description<br/>(patched into the saved photo)"]
    VD --> INJECT["Description injected as text turn"]
    INJECT --> LOCK
```

And add `PG` to the deterministic class line:

```
    class TF,PG,STALE,MENU deterministic
```

- [ ] **Step 2: Update the image branch notes**

In the `**\`image\`**` paragraph of `docs/message-flow.md` (line 84), after the sentence ending "the confidence gate stays in app code.", insert:

```
Every returned crop -- gate-passed or not -- is persisted as a
[Tongue Photo](../CONTEXT.md) in the standalone `tongue_photos` collection
([ADR 0007](adr/0007-tongue-photo-dataset-and-echo.md)), outside the memory
lifecycle. Gate-passed crops are echoed back beside the Assessment as a LINE
ImageMessage (Quick Reply rides on the image); the URL is a self-hosted
capability URL, `GET /tongue-photos/{photo_id}`, and delivery degrades one
rung at a time down to plain text -- the image never costs the user their
Assessment.
```

- [ ] **Step 3: Commit, and note the deployment step**

```bash
git add docs/message-flow.md
git commit -m "docs: add the Tongue Photo save/echo lane to the message flow"
```

Deployment note (manual, not committed): add `PUBLIC_BASE_URL=https://<cloudflared-tunnel-host>` to `.env` before live testing — with it unset the echo is silently disabled (by design), which is also the safe default for local runs.

---

## Self-Review Notes

- **Spec coverage:** schema fields (Task 2), BSON Binary not base64 (Task 2, global constraint), insert-after-detect/update-after-describe (Tasks 2, 5), below-gate kept but never described/echoed (Tasks 1, 5), UUID4 capability URL + unauthenticated endpoint + no enumeration (Tasks 3, 5), same JPEG both URL slots + Quick Reply on the image (Task 4), four-rung degrade chain (Task 4), save failures never surfaced (Task 5), retake/hiccup replies stay image-free (Task 5 structure), retention disclosure in the welcome message (Task 5), detector contract widening (Task 1), `line_message_id` stored (Task 2), `PUBLIC_BASE_URL` config + frozen-URL consequence documented (Tasks 5, 6).
- **Ordering:** Task 1 must land with its dispatcher gate fix in the same commit (otherwise below-gate crops would be assessed). Task 5 depends on Tasks 1, 2, and 4; Task 3 is independent after Task 2.
- **Type consistency check:** `CroppedTongue.passed_gate` (Task 1) ↔ `TonguePhoto.passed_gate` (Task 2) ↔ dispatcher `_save_tongue_photo` (Task 5). `TonguePhotoRepository.insert/set_description/get_jpeg` names match across Tasks 2, 3, 5. `reply_or_push(..., image_url=)` matches Tasks 4 and 5.
