from datetime import UTC, datetime, timedelta

from mongomock_motor import AsyncMongoMockClient

from app.memory.working_buffer import WorkingBufferRepository
from app.models.schemas import ConsultationTurn

# pop_if_stale compares against the real wall clock (datetime.now(UTC)), so
# fixture timestamps are anchored to it rather than to an arbitrary fixed
# "now" -- staleness is backdated relative to whenever the test actually runs.
# microsecond=0 avoids false negatives from BSON's millisecond-precision
# round-trip through the (mock) Mongo collection.
NOW = datetime.now(UTC).replace(microsecond=0)
GAP_HOURS = 6.0


def _repo():
    db = AsyncMongoMockClient()["test_db"]
    return WorkingBufferRepository(db), db


async def _backdate_last_activity(db, user_id: str, when: datetime) -> None:
    """Simulate the passage of time by writing a naive last_activity directly
    into the mock collection -- exactly what a real Mongo read-back looks like
    (mongomock_motor, like real Mongo without tz_aware=True, strips tzinfo)."""
    await db["working_buffer"].update_one(
        {"user_id": user_id}, {"$set": {"last_activity": when.replace(tzinfo=None)}}
    )


async def test_fresh_buffer_returns_none_and_leaves_buffer_intact():
    repo, _db = _repo()
    turn = ConsultationTurn(role="user", text="สวัสดี", timestamp=NOW)
    await repo.append_turn("U1", turn)

    result = await repo.pop_if_stale("U1", GAP_HOURS)

    assert result is None
    assert await repo.current_turns("U1") == [turn]


async def test_stale_buffer_returns_turns_and_clears_buffer():
    repo, db = _repo()
    turn = ConsultationTurn(role="user", text="นอนไม่หลับ", timestamp=NOW)
    await repo.append_turn("U1", turn)
    await _backdate_last_activity(db, "U1", NOW - timedelta(hours=GAP_HOURS + 1))

    result = await repo.pop_if_stale("U1", GAP_HOURS)

    assert result == [turn]
    assert await repo.current_turns("U1") == []


async def test_stale_buffer_returned_turn_timestamps_are_tz_aware():
    repo, db = _repo()
    turn = ConsultationTurn(role="user", text="นอนไม่หลับ", timestamp=NOW)
    await repo.append_turn("U1", turn)
    await _backdate_last_activity(db, "U1", NOW - timedelta(hours=GAP_HOURS + 1))

    result = await repo.pop_if_stale("U1", GAP_HOURS)

    assert result is not None
    assert all(t.timestamp.tzinfo is not None for t in result)
