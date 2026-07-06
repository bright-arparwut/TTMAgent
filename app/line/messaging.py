from linebot.v3.messaging import (
    ApiClient,
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    PushMessageRequest,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.config import Settings


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

    async def reply(self, reply_token: str, text: str) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.reply_message(
                ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=text)])
            )

    async def push(self, user_id: str, text: str) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
            )

    async def reply_or_push(self, *, reply_token: str, user_id: str, text: str) -> None:
        """Attempt the reply token; fall back to a push message if it's expired."""
        try:
            await self.reply(reply_token, text)
        except Exception:
            await self.push(user_id, text)

    async def download_content(self, message_id: str) -> bytes:
        """Fetch an image/media attachment's bytes from LINE's content API."""
        async with self._client() as client:
            blob_api = AsyncMessagingApiBlob(client)
            return await blob_api.get_message_content(message_id)


def sync_client(settings: Settings) -> ApiClient:
    """Synchronous client, for one-off scripts (e.g. RAG ingestion tooling)."""
    return ApiClient(Configuration(access_token=settings.line_channel_access_token))
