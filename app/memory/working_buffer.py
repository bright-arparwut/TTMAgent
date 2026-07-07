from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.schemas import ConsultationTurn

COLLECTION = "working_buffer"


class WorkingBufferRepository:
    """The raw, per-user turn buffer for the currently-open Consultation.

    Read by the spine each turn and replayed to the Advisor as
    within-Consultation memory (ADR 0005) -- the Advisor has no tool to
    query it. Never itself persisted long term -- see CONTEXT.md ->
    Consultation / Health Record. Closing is lazy: `pop_if_stale` is the
    only place a Consultation actually ends.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db[COLLECTION]

    async def pop_if_stale(
        self, user_id: str, gap_hours: float
    ) -> list[ConsultationTurn] | None:
        """If the existing buffer has been idle longer than gap_hours, delete
        it and return its turns for summarization. Otherwise leave it
        untouched and return None -- the Consultation is still open.
        """
        doc = await self._collection.find_one({"user_id": user_id})
        if doc is None:
            return None

        last_activity = doc["last_activity"]
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=UTC)

        gap = timedelta(hours=gap_hours)
        if datetime.now(UTC) - last_activity < gap:
            return None

        await self._collection.delete_one({"user_id": user_id})
        return [ConsultationTurn(**turn) for turn in doc["turns"]]

    async def append_turn(self, user_id: str, turn: ConsultationTurn) -> None:
        await self._collection.update_one(
            {"user_id": user_id},
            {
                "$push": {"turns": turn.model_dump()},
                "$set": {"last_activity": datetime.now(UTC)},
            },
            upsert=True,
        )

    async def current_turns(self, user_id: str) -> list[ConsultationTurn]:
        doc = await self._collection.find_one({"user_id": user_id})
        if doc is None:
            return []
        return [ConsultationTurn(**turn) for turn in doc["turns"]]
