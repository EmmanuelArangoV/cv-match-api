import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.path.join(_PROJECT_ROOT, ".env"), extra="ignore")

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

    # Twilio (llamadas de profiling — AMD sincrono + registro en ElevenLabs)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_api_url: str = "https://api.twilio.com"
    twilio_validate_signature: bool = True

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_base_url: str = ""  # override solo para tests (mock local); vacio en produccion
    elevenlabs_webhook_secret_transcription: str = ""

    # URL publica bajo la cual Twilio/ElevenLabs pueden alcanzar este backend (ngrok en dev)
    public_base_url: str = ""

    # Meta WhatsApp Business
    meta_whatsapp_api_url: str = "https://graph.facebook.com/v21.0"
    meta_whatsapp_phone_number_id: str = ""
    meta_whatsapp_access_token: str = ""
    meta_whatsapp_verify_token: str = ""
    meta_whatsapp_webhook_secret: str = ""
    whatsapp_template_fallback_enabled: bool = False

    # Business rules
    max_concurrent_calls: int = 4
    whatsapp_consent_timeout_hours: float = 24
    cv_batch_limit: int = 50
    max_cv_file_size_mb: int = 10
    profiling_delay_seconds: int = 86400  # Default 24h
    max_call_attempts: int = 3
    machine_detection_timeout: int = 10
    twilio_ring_timeout_seconds: int = 25

    # Watchdog de llamadas de profiling atascadas (ver check_stale_profiling_calls)
    watchdog_interval_seconds: int = 120
    stale_calling_timeout_seconds: int = 60
    stale_answered_timeout_seconds: int = 900

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"


settings = Settings()  # type: ignore[call-arg]
