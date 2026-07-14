import pytest

from app.config import Settings
from app.line.messaging import LineMessenger, build_image_message, build_text_message


def _settings() -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test")


def test_build_text_message_without_topics_has_no_quick_reply():
    message = build_text_message("สวัสดีค่ะ")
    assert message.text == "สวัสดีค่ะ"
    assert message.quick_reply is None


def test_build_text_message_renders_topics_as_quick_reply_buttons():
    topics = ("อาหารบำรุงธาตุไฟ", "ท่าบริหารตอนเช้า")
    message = build_text_message("คำตอบ", topics)
    items = message.quick_reply.items
    # Each button echoes its label back as the user's next message, so the
    # tap re-enters the normal text pipeline.
    assert [item.action.label for item in items] == list(topics)
    assert [item.action.text for item in items] == list(topics)


async def test_reply_or_push_forwards_topics_to_reply():
    messenger = LineMessenger(_settings())
    calls = []

    async def fake_reply(reply_token, text, topics=(), image_url=None):
        calls.append((reply_token, text, tuple(topics)))

    messenger.reply = fake_reply

    await messenger.reply_or_push(
        reply_token="R1", user_id="U1", text="คำตอบ", topics=("หัวข้อหนึ่ง",)
    )

    assert calls == [("R1", "คำตอบ", ("หัวข้อหนึ่ง",))]


async def test_reply_or_push_falls_back_to_push_with_topics():
    messenger = LineMessenger(_settings())
    pushed = []

    async def failing_reply(reply_token, text, topics=(), image_url=None):
        raise RuntimeError("reply token expired")

    async def fake_push(user_id, text, topics=(), image_url=None):
        pushed.append((user_id, text, tuple(topics)))

    messenger.reply = failing_reply
    messenger.push = fake_push

    await messenger.reply_or_push(
        reply_token="R1", user_id="U1", text="คำตอบ", topics=("หัวข้อหนึ่ง",)
    )

    assert pushed == [("U1", "คำตอบ", ("หัวข้อหนึ่ง",))]


async def test_push_failure_with_topics_degrades_to_plain_text():
    # A Quick Reply payload LINE rejects must never cost the user the reply
    # itself: one retry without topics, same text.
    messenger = LineMessenger(_settings())
    calls = []

    async def failing_reply(reply_token, text, topics=(), image_url=None):
        raise RuntimeError("reply token expired")

    async def flaky_push(user_id, text, topics=(), image_url=None):
        calls.append((user_id, text, tuple(topics)))
        if topics:
            raise RuntimeError("400 invalid quickReply")

    messenger.reply = failing_reply
    messenger.push = flaky_push

    await messenger.reply_or_push(
        reply_token="R1", user_id="U1", text="คำตอบ", topics=("หัวข้อหนึ่ง",)
    )

    assert calls == [("U1", "คำตอบ", ("หัวข้อหนึ่ง",)), ("U1", "คำตอบ", ())]


async def test_push_failure_without_topics_still_propagates():
    # Plain-text failures keep their pre-existing behavior: the exception
    # reaches the caller instead of being swallowed here.
    messenger = LineMessenger(_settings())

    async def failing_reply(reply_token, text, topics=(), image_url=None):
        raise RuntimeError("reply token expired")

    async def failing_push(user_id, text, topics=(), image_url=None):
        raise RuntimeError("LINE push outage")

    messenger.reply = failing_reply
    messenger.push = failing_push

    with pytest.raises(RuntimeError, match="LINE push outage"):
        await messenger.reply_or_push(reply_token="R1", user_id="U1", text="คำตอบ")


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
