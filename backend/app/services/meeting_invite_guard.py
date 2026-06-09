import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


_meeting_invite_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def meeting_invite_lock(call_id: str) -> AsyncIterator[None]:
    lock = _meeting_invite_locks.setdefault(call_id, asyncio.Lock())
    async with lock:
        yield
