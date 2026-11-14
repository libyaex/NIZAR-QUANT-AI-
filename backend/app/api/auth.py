"""Auth dependency: verifies the Supabase JWT from the frontend."""
import logging
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)


class AuthUser:
    def __init__(self, user_id: str, email: str = ""):
        self.id = user_id
        self.email = email


async def current_user(request: Request) -> AuthUser:
    """Validate the Supabase access token (Bearer) issued by the frontend."""
    auth: Optional[str] = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth.split(" ", 1)[1]
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={"apikey": settings.supabase_service_role_key, "Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        data = resp.json()
        return AuthUser(user_id=data["id"], email=data.get("email", ""))
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("auth check failed: %s", exc)
        raise HTTPException(status_code=401, detail="Auth failed")