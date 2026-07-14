from app.config import Settings
from app.line.messaging import LineMessenger, build_text_message


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

    async def fake_reply(reply_token, text, topics=()):
        calls.append((reply_token, text, tuple(topics)))

    messenger.reply = fake_reply

    await messenger.reply_or_push(
        reply_token="R1", user_id="U1", text="คำตอบ", topics=("หัวข้อหนึ่ง",)
    )

    assert calls == [("R1", "คำตอบ", ("หัวข้อหนึ่ง",))]


async def test_reply_or_push_falls_back_to_push_with_topics():
    messenger = LineMessenger(_settings())
    pushed = []

    async def failing_reply(reply_token, text, topics=()):
        raise RuntimeError("reply token expired")

    async def fake_push(user_id, text, topics=()):
        pushed.append((user_id, text, tuple(topics)))

    messenger.reply = failing_reply
    messenger.push = fake_push

    await messenger.reply_or_push(
        reply_token="R1", user_id="U1", text="คำตอบ", topics=("หัวข้อหนึ่ง",)
    )

    assert pushed == [("U1", "คำตอบ", ("หัวข้อหนึ่ง",))]
