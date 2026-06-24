import redis.asyncio as aioredis

from src.config import settings

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    ssl_cert_reqs=None,
)
