import ssl

from celery import Celery

from src.config import settings

celery_app = Celery(
    "riwi_match",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "src.infrastructure.workers.tasks.parse_cv",
        "src.infrastructure.workers.tasks.whatsapp",
        "src.infrastructure.workers.tasks.run_match",
        "src.infrastructure.workers.tasks.profiling",
    ],
)

_ssl_opts = {"ssl_cert_reqs": ssl.CERT_NONE}

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    timezone="America/Bogota",
    broker_use_ssl=_ssl_opts if settings.redis_url.startswith("rediss://") else {},
    redis_backend_use_ssl=_ssl_opts if settings.redis_url.startswith("rediss://") else {},
    beat_schedule={
        "check-stale-profiling-calls": {
            "task": "check_stale_profiling_calls",
            "schedule": settings.watchdog_interval_seconds,
        },
        "resolve-whatsapp-timeouts": {
            "task": "resolve_whatsapp_timeouts",
            "schedule": settings.watchdog_interval_seconds,
        },
    },
)
