import json

import redis
import redis.asyncio as aioredis

from src.config import settings

_is_tls = settings.redis_url.startswith("rediss://")

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    retry_on_timeout=False,
    socket_connect_timeout=5,
    socket_timeout=5,
    health_check_interval=30,
    socket_keepalive=True,
    **({"ssl_cert_reqs": "none", "ssl_check_hostname": False} if _is_tls else {}),
)

redis_client_sync: redis.Redis = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    retry_on_timeout=False,
    socket_connect_timeout=5,
    socket_timeout=5,
    health_check_interval=30,
    socket_keepalive=True,
    **({"ssl_cert_reqs": "none", "ssl_check_hostname": False} if _is_tls else {}),
)


def _get_cached_sync(key: str) -> str | None:
    try:
        value = redis_client_sync.get(key)
    except redis.RedisError:
        return None
    if value is None:
        return None
    return value if isinstance(value, str) else value.decode("utf-8")


def _set_cached_sync(key: str, value: str) -> None:
    try:
        redis_client_sync.setex(key, 900, value)
    except redis.RedisError:
        pass


async def _get_cached(key: str) -> str | None:
    try:
        value = await redis_client.get(key)
    except redis.RedisError:
        return None
    if value is None:
        return None
    return value if isinstance(value, str) else value.decode("utf-8")


async def _set_cached(key: str, value: str) -> None:
    try:
        await redis_client.setex(key, 900, value)
    except redis.RedisError:
        pass


def get_active_ai_prompt_sync(db, task_type: str, fallback_prompt: str) -> str:
    key = f"ai_prompt:active:{task_type}"
    cached = _get_cached_sync(key)
    if cached:
        return cached

    from sqlalchemy import select

    from src.infrastructure.db.models import AIPrompt

    prompt = db.execute(
        select(AIPrompt).where(AIPrompt.task_type == task_type, AIPrompt.is_active.is_(True))
    ).scalar_one_or_none()

    val = prompt.system_prompt_text if prompt else fallback_prompt
    _set_cached_sync(key, val)
    return val


async def get_active_ai_prompt(db, task_type: str, fallback_prompt: str) -> str:
    """Variante async de get_active_ai_prompt_sync, para llamarla desde endpoints FastAPI
    (AsyncSession) en vez de las tareas de Celery (Session sincrona)."""
    key = f"ai_prompt:active:{task_type}"
    cached = await _get_cached(key)
    if cached:
        return cached

    from sqlalchemy import select

    from src.infrastructure.db.models import AIPrompt

    result = await db.execute(
        select(AIPrompt).where(AIPrompt.task_type == task_type, AIPrompt.is_active.is_(True))
    )
    prompt = result.scalar_one_or_none()

    val = prompt.system_prompt_text if prompt else fallback_prompt
    await _set_cached(key, val)
    return val


def get_active_ai_model_sync(db, task_type: str, provider: str, fallback_model: str) -> str:
    key = f"ai_model:active:{task_type}:{provider}"
    cached = _get_cached_sync(key)
    if cached:
        return cached

    from sqlalchemy import select

    from src.infrastructure.db.models import AIModelConfiguration

    model = db.execute(
        select(AIModelConfiguration).where(
            AIModelConfiguration.task_type == task_type,
            AIModelConfiguration.provider == provider,
            AIModelConfiguration.is_active.is_(True),
        )
    ).scalar_one_or_none()

    val = model.model_name if model else fallback_model
    _set_cached_sync(key, val)
    return val


async def get_active_ai_model(db, task_type: str, provider: str, fallback_model: str) -> str:
    """Variante async de get_active_ai_model_sync, para llamarla desde endpoints FastAPI
    (AsyncSession) en vez de las tareas de Celery (Session sincrona)."""
    key = f"ai_model:active:{task_type}:{provider}"
    cached = await _get_cached(key)
    if cached:
        return cached

    from sqlalchemy import select

    from src.infrastructure.db.models import AIModelConfiguration

    result = await db.execute(
        select(AIModelConfiguration).where(
            AIModelConfiguration.task_type == task_type,
            AIModelConfiguration.provider == provider,
            AIModelConfiguration.is_active.is_(True),
        )
    )
    model = result.scalar_one_or_none()

    val = model.model_name if model else fallback_model
    await _set_cached(key, val)
    return val


def get_global_setting_sync(db, key: str, default_value: str) -> str:
    redis_key = f"global_setting:{key}"
    cached = _get_cached_sync(redis_key)
    if cached:
        return cached

    from src.infrastructure.db.models import GlobalBusinessSetting

    setting = db.query(GlobalBusinessSetting).filter_by(setting_key=key).first()

    val = setting.setting_value if setting else default_value

    # Cache it for 15 minutes
    _set_cached_sync(redis_key, val)
    return val


def get_global_setting_dict_sync(db, key: str, default_value: dict) -> dict:
    """Igual que get_global_setting_sync pero para settings cuyo valor es un dict
    (setting_value JSONB con múltiples campos, no un escalar)."""
    redis_key = f"global_setting:{key}"
    cached = _get_cached_sync(redis_key)
    if cached:
        return json.loads(cached)

    from src.infrastructure.db.models import GlobalBusinessSetting

    setting = db.query(GlobalBusinessSetting).filter_by(setting_key=key).first()

    val = setting.setting_value if setting else default_value

    _set_cached_sync(redis_key, json.dumps(val))
    return val
