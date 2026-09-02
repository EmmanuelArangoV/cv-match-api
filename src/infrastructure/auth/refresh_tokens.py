import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.infrastructure.auth.tokens import get_refresh_ttl
from src.infrastructure.cache.redis_client import redis_client

logger = logging.getLogger(__name__)

_PREFIX = "refresh:"


@dataclass(frozen=True)
class RefreshSession:
    user_id: str
    absolute_expires_at: int | None = None


async def store_refresh_token(
    token: str,
    user_id: str,
    *,
    absolute_expires_at: int | None = None,
) -> None:
    try:
        ttl = get_refresh_ttl()
        if absolute_expires_at is not None:
            remaining = absolute_expires_at - int(datetime.now(UTC).timestamp())
            if remaining <= 0:
                return
            ttl = min(ttl, remaining)
        value = json.dumps(
            {"user_id": user_id, "absolute_expires_at": absolute_expires_at},
            separators=(",", ":"),
        )
        await redis_client.setex(f"{_PREFIX}{token}", ttl, value)
    except Exception as e:
        logger.warning(f"Failed to store refresh token in Redis: {e}")


async def get_refresh_session(token: str) -> RefreshSession | None:
    try:
        value = await redis_client.get(f"{_PREFIX}{token}")
    except Exception as e:
        logger.warning(f"Failed to get refresh token from Redis: {e}")
        return None
    if not value:
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        # Compatibilidad con refresh tokens creados antes de guardar metadata SSO.
        return RefreshSession(user_id=value)
    if not isinstance(payload, dict) or not isinstance(payload.get("user_id"), str):
        return None
    absolute_expires_at = payload.get("absolute_expires_at")
    if absolute_expires_at is not None and not isinstance(absolute_expires_at, int):
        return None
    return RefreshSession(
        user_id=payload["user_id"],
        absolute_expires_at=absolute_expires_at,
    )


async def get_user_id_from_refresh(token: str) -> str | None:
    session = await get_refresh_session(token)
    return session.user_id if session else None


async def revoke_refresh_token(token: str) -> None:
    try:
        await redis_client.delete(f"{_PREFIX}{token}")
    except Exception as e:
        logger.warning(f"Failed to revoke refresh token in Redis: {e}")
