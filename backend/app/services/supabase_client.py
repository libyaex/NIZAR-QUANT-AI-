"""Supabase service-role client used only server-side.

The client is created once per process (singleton). Settings is a pydantic
model, which is NOT hashable, so it cannot be used directly as an lru_cache
key — that raised "TypeError: unhashable type: 'Settings'" on Railway.
Instead we cache on the hashable settings values (url + service-role key)
behind a lock, which keeps a single client instance without breaking the
FastAPI lifespan or any existing call signature.
"""
from threading import Lock
from typing import Optional, Tuple

from supabase import create_client

from app.config import Settings

_client = None
_cache_key: Optional[Tuple[str, str]] = None
_lock = Lock()


def get_supabase(settings: Settings):
    """Return the process-wide Supabase client.

    Accepts a Settings object (same signature as before). Rebuilds the
    client only if the underlying URL/key changed; otherwise returns the
    cached instance.
    """
    global _client, _cache_key
    key = (settings.supabase_url, settings.supabase_service_role_key)
    with _lock:
        if _client is None or _cache_key != key:
            _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
            _cache_key = key
        return _client