from datetime import UTC, datetime

from linebot.v3.webhooks import FollowEvent, MessageEvent

from app.advisor.graph import build_advisor_agent, run_advisor
from app.advisor.tools import build_health_record_tools
from app.config import Settings
from app.line.messaging import LineMessenger
from app.memory.db import get_database
from app.memory.health_record import HealthRecordRepository
from app.memory.relevance_gate import summarize_consultation
from app.memory.working_buffer import WorkingBufferRepository
from app.models.schemas import ConsultationTurn
from app.pipeline import user_queue
from app.rag.vector_store import retrieve_passages
from app.vision.describer import VisionDescriber
from app.vision.detector import TongueDetector

WELCOME_MESSAGE = (
    "สวัสดีค่ะ ดิฉันเป็นผู้ช่วยให้คำแนะนำด้านแพทย์แผนไทยเบื้องต้น "
    "ไม่ใช่แพทย์และไม่ได้ให้การวินิจฉัยทางการแพทย์ หากมีอาการรุนแรงหรือฉุกเฉิน "
    "กรุณาพบแพทย์หรือโทร 1669 ทันที"
)
RETAKE_GUIDANCE = (
    "ดิฉันมองไม่เห็นลิ้นในภาพนี้ชัดเจนค่ะ ลองถ่ายภาพลิ้นให้เต็มกรอบ แสงสว่างเพียงพอ "
    "และภาพไม่เบลอ แล้วส่งมาอีกครั้งนะคะ"
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
        reply_text = await _run_consultation_turn(user_id, event.message.text, settings)

    messenger = LineMessenger(settings)
    await messenger.reply_or_push(reply_token=event.reply_token, user_id=user_id, text=reply_text)


async def handle_image_message(event: MessageEvent, settings: Settings) -> None:
    user_id = event.source.user_id
    messenger = LineMessenger(settings)
    await messenger.show_loading(user_id)

    image_bytes = await messenger.download_content(event.message.id)

    detector = TongueDetector(settings)
    cropped = await detector.detect_and_crop(image_bytes)
    if cropped is None:
        # No tongue detected: guidance only, never a Tongue Assessment, and
        # not recorded in the working buffer -- see CONTEXT.md -> Tongue Assessment.
        await messenger.reply_or_push(
            reply_token=event.reply_token, user_id=user_id, text=RETAKE_GUIDANCE
        )
        return

    describer = VisionDescriber(settings)
    description = await describer.describe(cropped.image)

    turn_text = (
        "[User sent a tongue photo.] Vision Describer observations: "
        f"{description.model_dump_json()}. Please give a TTM Tongue Assessment "
        "based on these observations."
    )

    async with user_queue.lock_for(user_id):
        reply_text = await _run_consultation_turn(user_id, turn_text, settings)

    await messenger.reply_or_push(reply_token=event.reply_token, user_id=user_id, text=reply_text)


async def _run_consultation_turn(user_id: str, incoming_text: str, settings: Settings) -> str:
    """Shared turn logic for both text and (described) image turns: close a
    stale Consultation if one is waiting, append this turn, retrieve TTM
    context, run the Advisor, and append its reply. See CONTEXT.md ->
    Consultation and docs/design-decisions.html -> the text/image pipeline lanes.
    """
    db = get_database(settings)
    buffer_repo = WorkingBufferRepository(db)
    record_repo = HealthRecordRepository(db)

    stale_turns = await buffer_repo.pop_if_stale(user_id, settings.consultation_gap_hours)
    if stale_turns:
        gate_result = await summarize_consultation(stale_turns, user_id=user_id, settings=settings)
        if gate_result.has_health_content and gate_result.entry is not None:
            await record_repo.insert(gate_result.entry)

    await buffer_repo.append_turn(
        user_id, ConsultationTurn(role="user", text=incoming_text, timestamp=datetime.now(UTC))
    )

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
    )

    await buffer_repo.append_turn(
        user_id, ConsultationTurn(role="advisor", text=reply_text, timestamp=datetime.now(UTC))
    )
    return reply_text
