from src.infrastructure.auth.tokens import get_refresh_ttl
from src.infrastructure.cache.redis_client import redis_client

_PREFIX = "refresh:"


async def store_refresh_token(token: str, user_id: str) -> None:
    await redis_client.setex(f"{_PREFIX}{token}", get_refresh_ttl(), user_id)


async def get_user_id_from_refresh(token: str) -> str | None:
    return await redis_client.get(f"{_PREFIX}{token}")


async def revoke_refresh_token(token: str) -> None:
    await redis_client.delete(f"{_PREFIX}{token}")
