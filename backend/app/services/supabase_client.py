"""Supabase service-role client used only server-side."""
from functools import lru_cache

from supabase import create_client

from app.config import Settings


@lru_cache
def get_supabase(settings: Settings):
    return create_client(settings.supabase_url, settings.supabase_service_role_key)