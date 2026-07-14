import app.pipeline.dispatcher as dispatcher


def test_welcome_message_discloses_photo_retention():
    # ADR 0007: indefinite retention is disclosed by one sentence in the
    # follow welcome message.
    assert "วิจัย" in dispatcher.WELCOME_MESSAGE
