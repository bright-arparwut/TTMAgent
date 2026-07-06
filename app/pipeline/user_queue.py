import asyncio
from collections import defaultdict

# Per-user asyncio locks, in-process. Serializes turns from the same LINE
# user so two rapid messages can't race the working buffer / Health Record
# writes -- see docs/design-decisions.html -> "Per-user queue".
#
# In-process is sufficient at thesis scale (single app instance); a
# multi-instance deployment would need a distributed lock instead.
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def lock_for(user_id: str) -> asyncio.Lock:
    return _locks[user_id]
