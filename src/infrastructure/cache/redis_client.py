import redis.asyncio as aioredis

from src.config import settings

_is_tls = settings.redis_url.startswith("rediss://")

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    **({"ssl_cert_reqs": "none", "ssl_check_hostname": False} if _is_tls else {}),
)
