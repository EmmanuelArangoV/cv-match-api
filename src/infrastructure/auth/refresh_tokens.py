import logging

from src.infrastructure.auth.tokens import get_refresh_ttl
from src.infrastructure.cache.redis_client import redis_client

logger = logging.getLogger(__name__)

_PREFIX = "refresh:"


async def store_refresh_token(token: str, user_id: str) -> None:
    try:
        await redis_client.setex(f"{_PREFIX}{token}", get_refresh_ttl(), user_id)
    except Exception as e:
        logger.warning(f"Failed to store refresh token in Redis: {e}")


async def get_user_id_from_refresh(token: str) -> str | None:
    try:
        return await redis_client.get(f"{_PREFIX}{token}")
    except Exception as e:
        logger.warning(f"Failed to get refresh token from Redis: {e}")
        return None


async def revoke_refresh_token(token: str) -> None:
    try:
        await redis_client.delete(f"{_PREFIX}{token}")
    except Exception as e:
        logger.warning(f"Failed to revoke refresh token in Redis: {e}")
