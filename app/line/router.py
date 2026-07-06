from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from linebot.v3.webhook import InvalidSignatureError, WebhookParser
from linebot.v3.webhooks import FollowEvent, MessageEvent

from app.config import Settings, get_settings
from app.pipeline.dispatcher import handle_follow, handle_image_message, handle_text_message

router = APIRouter()


@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks) -> str:
    """LINE webhook entry point.

    Verifies the signature and parses events synchronously (fast), then hands
    each event to a background task and returns 200 immediately -- LINE never
    retries and the reply-token clock only starts once real work begins. See
    docs/design-decisions.html -> "Webhook returns 200 immediately".
    """
    settings = get_settings()
    body = (await request.body()).decode("utf-8")
    signature = request.headers.get("X-Line-Signature", "")

    parser = WebhookParser(settings.line_channel_secret)
    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError as exc:
        raise HTTPException(status_code=400, detail="Invalid signature") from exc

    for event in events:
        background_tasks.add_task(_dispatch, event, settings)

    return "OK"


async def _dispatch(event, settings: Settings) -> None:
    if isinstance(event, FollowEvent):
        await handle_follow(event, settings)
        return

    if isinstance(event, MessageEvent):
        message_type = event.message.type
        if message_type == "text":
            await handle_text_message(event, settings)
        elif message_type == "image":
            await handle_image_message(event, settings)
        # Other message types (sticker, location, ...) are intentionally
        # unhandled -- the Advisor scope is Thai TTM chat + tongue photos.
