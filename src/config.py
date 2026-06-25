import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(_PROJECT_ROOT, ".env"),
        extra="ignore"
    )

    # App
    app_env: str = "development"
    app_secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60

    # Database
    database_url: str
    database_url_sync: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Cloudflare R2
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "riwi-match"
    r2_public_url: str = ""

    # OpenAI
    openai_api_key: str = ""

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_webhook_secret: str = ""

    # Meta WhatsApp Business
    meta_whatsapp_api_url: str = "https://graph.facebook.com/v21.0"
    meta_whatsapp_phone_number_id: str = ""
    meta_whatsapp_access_token: str = ""
    meta_whatsapp_verify_token: str = ""
    meta_whatsapp_webhook_secret: str = ""

    # Business rules
    max_concurrent_calls: int = 4
    whatsapp_consent_timeout_hours: int = 24
    cv_batch_limit: int = 50

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"


settings = Settings()  # type: ignore[call-arg]
