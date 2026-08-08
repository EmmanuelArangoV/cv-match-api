"""Sonda de readiness para dependencias internas obligatorias."""

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.infrastructure.cache.redis_client import redis_client
from src.infrastructure.db.database import engine

router = APIRouter(tags=["Health"])


async def check_database() -> None:
    """Verifica que PostgreSQL acepte una consulta minima."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def check_redis() -> None:
    """Verifica que Redis responda al proceso API."""
    await redis_client.ping()


@router.get("/ready")
async def readiness() -> JSONResponse:
    """Reporta readiness sin exponer URLs, credenciales ni mensajes internos."""
    results = await asyncio.gather(check_database(), check_redis(), return_exceptions=True)
    checks = {
        "database": "ok" if not isinstance(results[0], BaseException) else "error",
        "redis": "ok" if not isinstance(results[1], BaseException) else "error",
    }
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )
