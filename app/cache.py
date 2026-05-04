"""Simple in-process TTL cache for dictionary/reference data."""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional


class TTLCache:
    def __init__(self):
        self._store: dict[str, tuple[Any, datetime]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires = entry
        if datetime.utcnow() >= expires:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600):
        async with self._lock:
            self._store[key] = (value, datetime.utcnow() + timedelta(seconds=ttl_seconds))

    async def invalidate(self, key: str):
        self._store.pop(key, None)


cache = TTLCache()
