"""Tests for the Supabase client factory.

Regression test for the Railway crash:
    TypeError: unhashable type: 'Settings'
caused by decorating get_supabase with @lru_cache while passing a pydantic
Settings object (unhashable) as the cache key.

Run locally with:  cd backend && python -m pytest tests -q
(no network access required — create_client only constructs the client object)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.services import supabase_client  # noqa: E402
from app.services.supabase_client import get_supabase  # noqa: E402


def _make_settings(url="https://example.supabase.co", key="service-role-key"):
    return Settings(supabase_url=url, supabase_service_role_key=key)


def test_get_supabase_accepts_real_settings_object():
    """The original bug: calling get_supabase with a Settings instance raised
    TypeError: unhashable type: 'Settings' at startup (app/main.py line 21).
    It must return a client instead of raising."""
    settings = _make_settings()
    client = get_supabase(settings)
    assert client is not None


def test_get_supabase_returns_same_singleton_instance():
    """The client must be created once per process for identical settings."""
    settings_a = _make_settings()
    settings_b = _make_settings()  # separate but equal Settings instance
    assert get_supabase(settings_a) is get_supabase(settings_b)


def test_get_supabase_rebuilds_only_when_settings_change():
    """Changing the underlying url/key rebuilds the client; same values reuse it."""
    before = get_supabase(_make_settings(url="https://one.supabase.co"))
    same = get_supabase(_make_settings(url="https://one.supabase.co"))
    other = get_supabase(_make_settings(url="https://two.supabase.co"))
    assert before is same
    assert before is not other
    # restore cached singleton for other tests in this process
    supabase_client.get_supabase(_make_settings(url="https://one.supabase.co"))


def test_settings_object_is_not_hashable_confirming_root_cause():
    """Documents why lru_cache cannot key on Settings directly."""
    settings = _make_settings()
    try:
        hash(settings)
    except TypeError:
        return  # expected: pydantic models are unhashable by default
    raise AssertionError("Settings became hashable; this regression test needs review")