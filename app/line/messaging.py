import logging
from collections.abc import Sequence

from linebot.v3.messaging import (
    ApiClient,
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    MessageAction,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.config import Settings

logger = logging.getLogger(__name__)


def build_text_message(text: str, topics: Sequence[str] = ()) -> TextMessage:
    """Render a reply with its Topic Menu as LINE Quick Reply buttons.

    Topics must already be capped (ADR 0006, enforced by
    app/advisor/topic_menu.py: at most 5 topics of <= 20 chars -- LINE
    rejects longer labels at the API, not in the SDK). Tapping a button
    sends its text as the user's next message.
    """
    if not topics:
        return TextMessage(text=text)
    items = [QuickReplyItem(action=MessageAction(label=topic, text=topic)) for topic in topics]
    return TextMessage(text=text, quickReply=QuickReply(items=items))


class LineMessenger:
    """Wraps reply-token-with-push-fallback and the loading animation.

    Reply tokens are single-use and expire quickly (see docs/design-decisions.html
    -> "Reply"); callers should attempt reply() first and treat its failure as the
    signal to fall back to push(), not decide up front.
    """

    def __init__(self, settings: Settings) -> None:
        self._configuration = Configuration(access_token=settings.line_channel_access_token)

    def _client(self) -> AsyncApiClient:
        return AsyncApiClient(self._configuration)

    async def show_loading(self, user_id: str, seconds: int = 60) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.show_loading_animation(
                ShowLoadingAnimationRequest(chatId=user_id, loadingSeconds=seconds)
            )

    async def reply(self, reply_token: str, text: str, topics: Sequence[str] = ()) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token, messages=[build_text_message(text, topics)]
                )
            )

    async def push(self, user_id: str, text: str, topics: Sequence[str] = ()) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.push_message(
                PushMessageRequest(to=user_id, messages=[build_text_message(text, topics)])
            )

    async def reply_or_push(
        self, *, reply_token: str, user_id: str, text: str, topics: Sequence[str] = ()
    ) -> None:
        """Attempt the reply token; fall back to a push message if it's expired.

        A rejected Quick Reply payload must never cost the user the reply
        itself, so a failed push WITH topics is retried once as plain text
        (the same degrade-to-text philosophy the Topic Menu parser follows).
        """
        try:
            await self.reply(reply_token, text, topics)
            return
        except Exception:
            logger.warning("LINE reply failed for user %s; falling back to push", user_id)
        try:
            await self.push(user_id, text, topics)
        except Exception:
            if not topics:
                raise
            logger.warning(
                "LINE push with Quick Reply failed for user %s; retrying without topics",
                user_id,
                exc_info=True,
            )
            await self.push(user_id, text)

    async def download_content(self, message_id: str) -> bytes:
        """Fetch an image/media attachment's bytes from LINE's content API."""
        async with self._client() as client:
            blob_api = AsyncMessagingApiBlob(client)
            return await blob_api.get_message_content(message_id)


def sync_client(settings: Settings) -> ApiClient:
    """Synchronous client, for one-off scripts (e.g. RAG ingestion tooling)."""
    return ApiClient(Configuration(access_token=settings.line_channel_access_token))
