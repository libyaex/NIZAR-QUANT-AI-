"""Supabase service-role client (server-side only).

If Supabase is not configured (or the client cannot be built) a ``NullDB`` is
returned so the market engine and public API still run; routes that need the
database answer 503 with a clear message instead of crashing the service.
"""
import logging
from threading import Lock
from typing import Any, Optional, Tuple

from app.config import Settings

logger = logging.getLogger(__name__)

_client: Any = None
_cache_key: Optional[Tuple[str, str]] = None
_lock = Lock()


class _Result:
    data: list = []


class _NullQuery:
    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return _Result()


class NullDB:
    """Stand-in used when Supabase is unavailable."""
    is_null = True

    def table(self, _name):
        return _NullQuery()


def get_supabase(settings: Settings):
    global _client, _cache_key
    key = (settings.supabase_url, settings.supabase_service_role_key)
    with _lock:
        if _client is not None and _cache_key == key:
            return _client
        if not all(key):
            logger.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set - running without a database")
            _client, _cache_key = NullDB(), key
            return _client
        try:
            from supabase import create_client
            _client = create_client(*key)
        except Exception as exc:
            logger.error("Supabase client could not be created: %s", exc)
            _client = NullDB()
        _cache_key = key
        return _client


def db_ready(db) -> bool:
    return not getattr(db, "is_null", False)
