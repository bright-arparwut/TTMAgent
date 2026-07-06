from datetime import UTC, date, datetime, time

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.schemas import HealthRecordEntry

COLLECTION = "health_records"


class HealthRecordRepository:
    """The only persistent memory (see docs/adr/0002-health-record-only-memory.md).

    Writes happen exactly once, deterministically, at Consultation close
    (via the Relevance Gate) -- never through an Advisor tool call. Reads
    serve both the auto-injection at Consultation start and the Advisor's
    two read-only tools.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db[COLLECTION]

    async def insert(self, entry: HealthRecordEntry) -> None:
        await self._collection.insert_one(entry.model_dump())

    async def recent(self, user_id: str, count: int) -> list[HealthRecordEntry]:
        cursor = (
            self._collection.find({"user_id": user_id})
            .sort("consultation_date", -1)
            .limit(count)
        )
        return [HealthRecordEntry(**doc) async for doc in cursor]

    async def get_by_date(self, user_id: str, day: date) -> list[HealthRecordEntry]:
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = datetime.combine(day, time.max, tzinfo=UTC)
        cursor = self._collection.find(
            {"user_id": user_id, "consultation_date": {"$gte": start, "$lte": end}}
        )
        return [HealthRecordEntry(**doc) async for doc in cursor]

    async def all_for_user(self, user_id: str) -> list[HealthRecordEntry]:
        """All entries chronologically -- the replay source for rebuilding
        the Health Profile projection (ADR 0003)."""
        cursor = self._collection.find({"user_id": user_id}).sort("consultation_date", 1)
        return [HealthRecordEntry(**doc) async for doc in cursor]

    async def search(self, user_id: str, query: str, limit: int = 10) -> list[HealthRecordEntry]:
        """Case-insensitive substring search across the free-text fields.

        Fine at thesis scale (hundreds of entries per user, at most). A
        proper text index is the upgrade path if this needs to scale.
        """
        pattern = {"$regex": query, "$options": "i"}
        cursor = self._collection.find(
            {
                "user_id": user_id,
                "$or": [
                    {"chief_complaint": pattern},
                    {"symptoms": pattern},
                    {"advice_given": pattern},
                    {"conversation_summary": pattern},
                ],
            }
        ).limit(limit)
        return [HealthRecordEntry(**doc) async for doc in cursor]
