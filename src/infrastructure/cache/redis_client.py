import redis.asyncio as aioredis

from src.config import settings

_is_tls = settings.redis_url.startswith("rediss://")

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    **({"ssl_cert_reqs": "none", "ssl_check_hostname": False} if _is_tls else {}),
)
import redis

redis_client_sync: redis.Redis = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    **({"ssl_cert_reqs": "none", "ssl_check_hostname": False} if _is_tls else {}),
)

def get_active_ai_prompt_sync(db, task_type: str, fallback_prompt: str) -> str:
    key = f"ai_prompt:active:{task_type}"
    cached = redis_client_sync.get(key)
    if cached:
        return cached

    from sqlalchemy import select

    from src.infrastructure.db.models import AIPrompt
    prompt = db.execute(
        select(AIPrompt).where(AIPrompt.task_type == task_type, AIPrompt.is_active == True)
    ).scalar_one_or_none()
    
    val = prompt.system_prompt_text if prompt else fallback_prompt
    redis_client_sync.setex(key, 900, val) # 15 minutes TTL
    return val

def get_active_ai_model_sync(db, task_type: str, provider: str, fallback_model: str) -> str:
    key = f"ai_model:active:{task_type}:{provider}"
    cached = redis_client_sync.get(key)
    if cached:
        return cached

    from sqlalchemy import select

    from src.infrastructure.db.models import AIModelConfiguration
    model = db.execute(
        select(AIModelConfiguration).where(
            AIModelConfiguration.task_type == task_type,
            AIModelConfiguration.provider == provider,
            AIModelConfiguration.is_active == True,
        )
    ).scalar_one_or_none()
    
    val = model.model_name if model else fallback_model
    redis_client_sync.setex(key, 900, val) # 15 minutes TTL
    return val


def get_global_setting_sync(db, key: str, default_value: str) -> str:
    redis_key = f"global_setting:{key}"
    cached = redis_client_sync.get(redis_key)
    if cached:
        return cached.decode('utf-8')
    
    from src.infrastructure.db.models import GlobalBusinessSetting
    setting = db.query(GlobalBusinessSetting).filter_by(setting_key=key).first()
    
    val = setting.setting_value if setting else default_value
    
    # Cache it for 15 minutes
    redis_client_sync.setex(redis_key, 900, val)
    return val
