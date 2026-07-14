import logging
import uuid
from datetime import UTC, datetime

from linebot.v3.webhooks import FollowEvent, MessageEvent

from app.advisor.graph import build_advisor_agent, run_advisor
from app.advisor.tools import build_health_record_tools
from app.advisor.topic_menu import ParsedReply, split_topic_menu
from app.config import Settings
from app.line.messaging import LineMessenger
from app.memory.db import get_database
from app.memory.health_profile import HealthProfileRepository, empty_profile
from app.memory.health_record import HealthRecordRepository
from app.memory.profile_render import render_profile
from app.memory.profile_updater import update_profile_from_entry
from app.memory.relevance_gate import summarize_consultation
from app.memory.working_buffer import WorkingBufferRepository
from app.models.schemas import ConsultationTurn, TongueDescription, TonguePhoto
from app.pipeline import user_queue
from app.rag.vector_store import retrieve_passages
from app.tongue_photos.repository import TonguePhotoRepository
from app.vision.crop import encode_jpeg
from app.vision.describer import VisionDescriber
from app.vision.detector import CroppedTongue, TongueDetector

logger = logging.getLogger(__name__)

WELCOME_MESSAGE = (
    "สวัสดีค่ะ ดิฉันเป็นผู้ช่วยให้คำแนะนำด้านแพทย์แผนไทยเบื้องต้น "
    "ไม่ใช่แพทย์และไม่ได้ให้การวินิจฉัยทางการแพทย์ หากมีอาการรุนแรงหรือฉุกเฉิน "
    "กรุณาพบแพทย์หรือโทร 1669 ทันที "
    "ทั้งนี้ ภาพลิ้นที่ส่งเข้ามาเพื่อรับการประเมินจะถูกจัดเก็บไว้เพื่อการวิจัยค่ะ"
)
RETAKE_GUIDANCE = (
    "ดิฉันมองไม่เห็นลิ้นในภาพนี้ชัดเจนค่ะ ลองถ่ายภาพลิ้นให้เต็มกรอบ แสงสว่างเพียงพอ "
    "และภาพไม่เบลอ แล้วส่งมาอีกครั้งนะคะ"
)
SYSTEM_HICCUP_MESSAGE = (
    "ขออภัยค่ะ ระบบวิเคราะห์ภาพขัดข้องชั่วคราว กรุณาลองส่งภาพอีกครั้งภายหลังนะคะ"
)


async def handle_follow(event: FollowEvent, settings: Settings) -> None:
    """One-time disclaimer on the LINE `follow` event -- see
    CONTEXT.md -> TTM Self-Care Advisor and docs/design-decisions.html -> "Safety".
    """
    messenger = LineMessenger(settings)
    await messenger.reply_or_push(
        reply_token=event.reply_token, user_id=event.source.user_id, text=WELCOME_MESSAGE
    )


async def handle_text_message(event: MessageEvent, settings: Settings) -> None:
    user_id = event.source.user_id
    async with user_queue.lock_for(user_id):
        parsed = await _run_consultation_turn(user_id, event.message.text, settings)

    messenger = LineMessenger(settings)
    await messenger.reply_or_push(
        reply_token=event.reply_token,
        user_id=user_id,
        text=parsed.visible_text,
        topics=parsed.topics,
    )


async def handle_image_message(event: MessageEvent, settings: Settings) -> None:
    user_id = event.source.user_id
    messenger = LineMessenger(settings)
    try:
        await messenger.show_loading(user_id)
    except Exception:
        # The loading animation is cosmetic -- its failure must not cost the
        # user their Tongue Assessment.
        logger.warning("Loading animation failed for user %s", user_id, exc_info=True)

    try:
        image_bytes = await messenger.download_content(event.message.id)
        detector = TongueDetector(settings)
        cropped = await detector.detect_and_crop(image_bytes)
    except Exception:
        # Content download or detector outage must read as a system hiccup,
        # never as "your photo is bad" -- see
        # docs/adr/0004-serverless-workflow-crop.md.
        logger.exception("Vision pipeline failed for user %s", user_id)
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=SYSTEM_HICCUP_MESSAGE
        )
        return

    photo_id = None
    if cropped is not None:
        photo_id = await _save_tongue_photo(cropped, event.message.id, user_id, settings)

    if cropped is None or not cropped.passed_gate:
        # No tongue, or detected but below the confidence gate: guidance
        # only, never a Tongue Assessment (and below-gate crops are never
        # described or echoed -- ADR 0007), not recorded in the buffer.
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=RETAKE_GUIDANCE
        )
        return

    try:
        describer = VisionDescriber(settings)
        description = await describer.describe(cropped.image)
    except Exception:
        # Describer outage: same hiccup remedy, but the photo is already on
        # record with description null, marking exactly which stage failed.
        logger.exception("Vision describer failed for user %s", user_id)
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=SYSTEM_HICCUP_MESSAGE
        )
        return

    await _save_description(photo_id, description, settings)

    turn_text = (
        "[User sent a tongue photo.] Vision Describer observations: "
        f"{description.model_dump_json()}. Please give a TTM Tongue Assessment "
        "based on these observations."
    )

    async with user_queue.lock_for(user_id):
        parsed = await _run_consultation_turn(user_id, turn_text, settings)

    await messenger.reply_or_push(
        reply_token=event.reply_token,
        user_id=user_id,
        text=parsed.visible_text,
        topics=parsed.topics,
        image_url=_photo_url(photo_id, settings),
    )


async def _save_tongue_photo(
    cropped: CroppedTongue, message_id: str, user_id: str, settings: Settings
) -> str | None:
    """Persist the crop the moment detection succeeds (ADR 0007): dataset
    capture is independent of the gate, the describer, and the echo. Returns
    the photo_id, or None when the save failed -- a Mongo write error is
    logged, never surfaced, and the caller skips the echo so LINE is never
    handed a URL that would 404.
    """
    photo = TonguePhoto(
        # Capability URL id: UUID4, never a Mongo ObjectId (enumerable).
        photo_id=str(uuid.uuid4()),
        user_id=user_id,
        image=encode_jpeg(cropped.image),
        captured_at=datetime.now(UTC),
        confidence=cropped.confidence,
        passed_gate=cropped.passed_gate,
        line_message_id=message_id,
    )
    try:
        await TonguePhotoRepository(get_database(settings)).insert(photo)
    except Exception:
        logger.exception("Tongue Photo save failed for user %s", user_id)
        return None
    return photo.photo_id


async def _save_description(
    photo_id: str | None, description: TongueDescription, settings: Settings
) -> None:
    """Patch the Tongue Description into an already-saved photo. Best-effort
    for the same reason as _save_tongue_photo: never costs the user a turn."""
    if photo_id is None:
        return
    try:
        await TonguePhotoRepository(get_database(settings)).set_description(
            photo_id, description
        )
    except Exception:
        logger.exception("Tongue Description patch failed for photo %s", photo_id)


def _photo_url(photo_id: str | None, settings: Settings) -> str | None:
    if photo_id is None or not settings.public_base_url:
        return None
    return f"{settings.public_base_url.rstrip('/')}/tongue-photos/{photo_id}"


async def _run_consultation_turn(
    user_id: str, incoming_text: str, settings: Settings
) -> ParsedReply:
    """Shared turn logic for both text and (described) image turns: close a
    stale Consultation if one is waiting, append this turn, retrieve TTM
    context, run the Advisor, and append its reply. See CONTEXT.md ->
    Consultation and docs/design-decisions.html -> the text/image pipeline lanes.
    """
    db = get_database(settings)
    buffer_repo = WorkingBufferRepository(db)
    record_repo = HealthRecordRepository(db)
    profile_repo = HealthProfileRepository(db)

    stale_turns = await buffer_repo.pop_if_stale(user_id, settings.consultation_gap_hours)
    if stale_turns:
        gate_result = await summarize_consultation(stale_turns, user_id=user_id, settings=settings)
        if gate_result.has_health_content and gate_result.entry is not None:
            await record_repo.insert(gate_result.entry)
            if settings.health_profile_enabled:
                # The only Health Profile write path: gate-passed close (ADR 0003).
                await update_profile_from_entry(
                    profile_repo, user_id=user_id, entry=gate_result.entry, settings=settings
                )

    # Load prior turns BEFORE appending this one (ADR 0005): history is
    # exactly the turns that precede the incoming message. Capped at read
    # time only -- the Relevance Gate still sees the full buffer at close.
    # cap=0 disables replay (the memory-ablation arm); a plain negative
    # slice would hit Python's -0 == 0 trap and replay everything.
    max_turns = settings.advisor_history_max_turns
    prior_turns = await buffer_repo.current_turns(user_id)
    history = prior_turns[-max_turns:] if max_turns > 0 else []

    await buffer_repo.append_turn(
        user_id, ConsultationTurn(role="user", text=incoming_text, timestamp=datetime.now(UTC))
    )

    health_profile_block = ""
    if settings.health_profile_enabled:
        now = datetime.now(UTC)
        profile = await profile_repo.get(user_id) or empty_profile(user_id, now)
        health_profile_block = render_profile(profile, today=now.date())

    recent_entries = await record_repo.recent(user_id, settings.health_record_inject_count)
    recent_summary = "\n".join(entry.conversation_summary for entry in recent_entries)
    passages = await retrieve_passages(incoming_text)

    tools = build_health_record_tools(record_repo, user_id)
    agent = build_advisor_agent(settings, tools)
    reply_text = await run_advisor(
        agent,
        user_message=incoming_text,
        retrieved_passages=passages,
        recent_records_summary=recent_summary,
        health_profile_block=health_profile_block,
        history=history,
    )

    # The raw reply -- delimiter block included -- goes into the Working
    # Buffer so the Advisor can resolve "ข้อสอง" after LINE hides the
    # buttons (ADR 0006). Only the LINE transport sees the split.
    parsed = split_topic_menu(reply_text)
    await buffer_repo.append_turn(
        user_id,
        ConsultationTurn(role="advisor", text=parsed.raw_text, timestamp=datetime.now(UTC)),
    )
    return parsed
