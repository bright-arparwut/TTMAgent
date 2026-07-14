import logging
from collections.abc import Sequence

from linebot.v3.messaging import (
    ApiClient,
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    ImageMessage,
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

    async def download_content(self, message_id: str) -> bytes:
        """Fetch an image/media attachment's bytes from LINE's content API."""
        async with self._client() as client:
            blob_api = AsyncMessagingApiBlob(client)
            return await blob_api.get_message_content(message_id)


def sync_client(settings: Settings) -> ApiClient:
    """Synchronous client, for one-off scripts (e.g. RAG ingestion tooling)."""
    return ApiClient(Configuration(access_token=settings.line_channel_access_token))
