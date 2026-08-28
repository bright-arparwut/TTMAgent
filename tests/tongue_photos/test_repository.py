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
        color="แดง",
        coating="ฝ้าขาวบาง",
        size="ปกติ",
        shape="ปกติ",
        spots="ไม่มีจุด",
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
    assert doc["description"]["color"] == "แดง"
    assert bytes(doc["image"]) == JPEG  # image untouched by the patch


async def test_below_gate_crop_is_stored_with_passed_gate_false():
    repo, db = _repo()
    await repo.insert(_photo(passed_gate=False, confidence=0.3))

    doc = await db["tongue_photos"].find_one({"photo_id": _photo().photo_id})
    assert doc["passed_gate"] is False


def test_encode_jpeg_produces_decodable_jpeg_bytes():
    from io import BytesIO

    from PIL import Image

    from app.vision.crop import encode_jpeg

    image = Image.new("RGB", (16, 16), (200, 60, 60))

    raw = encode_jpeg(image)

    round_tripped = Image.open(BytesIO(raw))
    assert round_tripped.format == "JPEG"
    assert round_tripped.size == (16, 16)
