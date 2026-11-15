"""Auth dependency: verifies the Supabase access token sent by the frontend."""
import logging
import time
from typing import Dict, Optional, Tuple

import httpx
from fastapi import HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)
_CACHE: Dict[str, Tuple[float, "AuthUser"]] = {}
_TTL = 60.0


class AuthUser:
    def __init__(self, user_id: str, email: str = ""):
        self.id = user_id
        self.email = email


async def current_user(request: Request) -> AuthUser:
    auth: Optional[str] = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in required")
    token = auth.split(" ", 1)[1].strip()
    hit = _CACHE.get(token)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Server is missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={"apikey": settings.supabase_service_role_key, "Authorization": f"Bearer {token}"})
    except Exception as exc:
        logger.warning("auth check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Auth service unreachable")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Session expired - sign in again")
    data = resp.json()
    user = AuthUser(user_id=data["id"], email=data.get("email", ""))
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[token] = (time.time(), user)
    return user
