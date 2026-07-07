"""Send a correctly-signed LINE webhook to a locally running server.

Signs the request body exactly the way LINE does -- base64(HMAC-SHA256(
channel_secret, raw_body)) -- using the channel secret from the app's own
config (.env), so a running `uvicorn app.main:app` accepts it.

Usage (server must be running -- `uv run uvicorn app.main:app --reload`):

    uv run python scripts/send_webhook.py text "@example_bot Good Morning!!"
    uv run python scripts/send_webhook.py image
    uv run python scripts/send_webhook.py follow
    uv run python scripts/send_webhook.py text "หิว" --url http://localhost:8000/webhook

Pass --bad-signature to confirm the endpoint rejects a tampered request (400).
"""

import argparse
import base64
import hashlib
import hmac
import json
import sys

import httpx

from app.config import get_settings

REPLY_TOKEN = "00000000000000000000000000000000"
USER_ID = "U11111111111111111111111111111111"


def _base_event(**overrides: object) -> dict:
    event = {
        "mode": "active",
        "timestamp": 1_700_000_000_000,
        "source": {"type": "user", "userId": USER_ID},
        "webhookEventId": "01FZ74A0000000000000000000",
        "deliveryContext": {"isRedelivery": False},
        "replyToken": REPLY_TOKEN,
    }
    event.update(overrides)
    return event


def _build_event(kind: str, text: str) -> dict:
    if kind == "text":
        return _base_event(
            type="message",
            message={"id": "1", "type": "text", "quoteToken": "q", "text": text},
        )
    if kind == "image":
        return _base_event(
            type="message",
            message={
                "id": "1",
                "type": "image",
                "quoteToken": "q",
                "contentProvider": {"type": "line"},
            },
        )
    if kind == "follow":
        return _base_event(type="follow", follow={"isUnblocked": True})
    raise SystemExit(f"unknown event kind: {kind!r} (use text | image | follow)")


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["text", "image", "follow"])
    parser.add_argument("text", nargs="?", default="สวัสดีค่ะ", help="text for a text event")
    parser.add_argument("--url", default="http://localhost:8000/webhook")
    parser.add_argument(
        "--bad-signature", action="store_true", help="send a wrong signature (expect 400)"
    )
    args = parser.parse_args()

    secret = get_settings().line_channel_secret
    if not secret:
        raise SystemExit("line_channel_secret is empty -- set LINE_CHANNEL_SECRET in .env")

    body = json.dumps({"destination": "U" + "0" * 32, "events": [_build_event(args.kind, args.text)]})
    signature = _sign(body, "wrong-secret" if args.bad_signature else secret)

    response = httpx.post(
        args.url,
        content=body,
        headers={"Content-Type": "application/json", "X-Line-Signature": signature},
        timeout=10.0,
    )
    print(f"POST {args.url} -> {response.status_code} {response.text}")
    # Non-2xx is a failure worth a non-zero exit for scripting, except the
    # deliberate --bad-signature probe where 400 is the expected success.
    ok = response.status_code == 400 if args.bad_signature else response.is_success
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
