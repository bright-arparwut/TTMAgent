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
