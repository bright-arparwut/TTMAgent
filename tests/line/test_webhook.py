"""Tests for the LINE webhook HTTP boundary (app/line/router.py).

These lock in the transport contract: X-Line-Signature verification, the
synchronous parse -> 200 "OK" response, and event routing to the background
dispatcher. Handlers are stubbed so no real Advisor/DB/vision work runs; the
tests assert only what the webhook layer is responsible for.

Current behavior is captured as-is -- including that a text message's mention
prefix (e.g. "@example_bot") flows through verbatim to handle_text_message.
"""

import base64
import hashlib
import hmac
import json
import warnings

# Importing fastapi.testclient emits a StarletteDeprecationWarning about httpx;
# it is harness noise unrelated to what we test -- keep test output pristine.
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.line.router as router  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import app  # noqa: E402

CHANNEL_SECRET = "test-channel-secret"


def _settings() -> Settings:
    return Settings(
        line_channel_secret=CHANNEL_SECRET,
        line_channel_access_token="test-access-token",
    )


def _sign(body: str, secret: str = CHANNEL_SECRET) -> str:
    """LINE signature: base64(HMAC-SHA256(secret, body)) over the raw body."""
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _envelope(*events: dict) -> str:
    """A full LINE webhook body wrapping the given event objects."""
    return json.dumps({"destination": "Udestination0000000000000000000000", "events": list(events)})


def _base_event(**overrides: object) -> dict:
    event = {
        "mode": "active",
        "timestamp": 1_700_000_000_000,
        "source": {"type": "user", "userId": "U1111111111111111111111111111111"},
        "webhookEventId": "01FZ74A0000000000000000000",
        "deliveryContext": {"isRedelivery": False},
        "replyToken": "reply-token-0000000000000000",
    }
    event.update(overrides)
    return event


def _text_event(text: str = "@example_bot Good Morning!!") -> dict:
    return _base_event(
        type="message",
        message={
            "id": "444573844083572737",
            "type": "text",
            "quoteToken": "q3Plxr4AgKd",
            "text": text,
            "mention": {
                "mentionees": [
                    {
                        "index": 0,
                        "length": 12,
                        "userId": "Ubotbotbotbotbotbotbotbotbotbotbot",
                        "type": "user",
                        "isSelf": True,
                    }
                ]
            },
        },
    )


def _image_event() -> dict:
    return _base_event(
        type="message",
        message={
            "id": "444573844083572738",
            "type": "image",
            "quoteToken": "q3Plxr4AgKd",
            "contentProvider": {"type": "line"},
        },
    )


def _follow_event() -> dict:
    return _base_event(type="follow", follow={"isUnblocked": True})


def _sticker_event() -> dict:
    # A fully-formed sticker message: parses as a real MessageEvent whose
    # message.type is "sticker", so it exercises _dispatch's "other message
    # types intentionally unhandled" branch (not the UnknownEvent fallback).
    return _base_event(
        type="message",
        message={
            "id": "444573844083572739",
            "type": "sticker",
            "quoteToken": "q3Plxr4AgKd",
            "packageId": "446",
            "stickerId": "1988",
            "stickerResourceType": "STATIC",
        },
    )


@pytest.fixture
def routed(monkeypatch) -> dict[str, list]:
    """Stub the three handlers and the settings lookup.

    Returns a dict of the events each handler received, so tests assert which
    handler fired (and with what event) without any real work running.
    """
    calls: dict[str, list] = {"text": [], "image": [], "follow": []}

    async def record_text(event, settings):
        calls["text"].append(event)

    async def record_image(event, settings):
        calls["image"].append(event)

    async def record_follow(event, settings):
        calls["follow"].append(event)

    monkeypatch.setattr(router, "get_settings", _settings)
    monkeypatch.setattr(router, "handle_text_message", record_text)
    monkeypatch.setattr(router, "handle_image_message", record_image)
    monkeypatch.setattr(router, "handle_follow", record_follow)
    return calls


@pytest.fixture
def client() -> TestClient:
    # TestClient runs background tasks synchronously after the response is
    # produced, so recorded calls are visible once client.post() returns.
    return TestClient(app)


def _post(client: TestClient, body: str, signature: str | None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Line-Signature"] = signature
    return client.post("/webhook", content=body, headers=headers)


def test_valid_signature_returns_200_and_routes_text(client, routed):
    body = _envelope(_text_event())

    response = _post(client, body, _sign(body))

    assert response.status_code == 200
    assert response.json() == "OK"
    assert len(routed["text"]) == 1
    # Mention prefix is passed through verbatim (current behavior).
    assert routed["text"][0].message.text == "@example_bot Good Morning!!"
    assert routed["image"] == [] and routed["follow"] == []


def test_valid_signature_routes_image_message(client, routed):
    body = _envelope(_image_event())

    response = _post(client, body, _sign(body))

    assert response.status_code == 200
    assert len(routed["image"]) == 1
    assert routed["text"] == [] and routed["follow"] == []


def test_valid_signature_routes_follow_event(client, routed):
    body = _envelope(_follow_event())

    response = _post(client, body, _sign(body))

    assert response.status_code == 200
    assert len(routed["follow"]) == 1
    assert routed["text"] == [] and routed["image"] == []


def test_unknown_message_type_is_ignored(client, routed):
    # Sticker (and other non-text/image messages) are intentionally unhandled.
    body = _envelope(_sticker_event())

    response = _post(client, body, _sign(body))

    assert response.status_code == 200
    assert routed["text"] == [] and routed["image"] == [] and routed["follow"] == []


def test_multiple_events_are_each_dispatched(client, routed):
    body = _envelope(_text_event("first"), _image_event(), _text_event("second"))

    response = _post(client, body, _sign(body))

    assert response.status_code == 200
    assert [e.message.text for e in routed["text"]] == ["first", "second"]
    assert len(routed["image"]) == 1


def test_invalid_signature_returns_400_and_does_not_dispatch(client, routed):
    body = _envelope(_text_event())

    response = _post(client, body, _sign(body, secret="wrong-secret"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid signature"
    assert routed["text"] == []


def test_missing_signature_header_returns_400(client, routed):
    body = _envelope(_text_event())

    response = _post(client, body, signature=None)

    assert response.status_code == 400
    assert routed["text"] == []


def test_tampered_body_fails_signature_of_original(client, routed):
    original = _envelope(_text_event("hello"))
    signature = _sign(original)
    tampered = _envelope(_text_event("goodbye"))

    response = _post(client, tampered, signature)

    assert response.status_code == 400
    assert routed["text"] == []
