import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter

from src.api.deps import RequireAdmin
from src.config import settings
from src.infrastructure.storage.r2_client import _get_client as get_r2_client
from src.infrastructure.voice.elevenlabs_client import get_elevenlabs_client
from src.infrastructure.voice.twilio_client import _get_client as get_twilio_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


async def check_twilio() -> dict[str, str]:
    try:
        def _check():
            client = get_twilio_client()
            # Petición rápida para validar credenciales
            client.api.v2010.accounts(settings.twilio_account_sid).fetch()
        
        await asyncio.to_thread(_check)
        return {"status": "ok", "details": "Conectado"}
    except Exception as e:
        logger.error(f"Twilio health check failed: {e}")
        return {"status": "error", "details": str(e)}


async def check_elevenlabs() -> dict[str, str]:
    try:
        def _check():
            client = get_elevenlabs_client()
            client.user.get()
        
        await asyncio.to_thread(_check)
        return {"status": "ok", "details": "Conectado"}
    except Exception as e:
        logger.error(f"ElevenLabs health check failed: {e}")
        return {"status": "error", "details": str(e)}


async def check_meta_whatsapp() -> dict[str, str]:
    try:
        # Petición ligera a Graph API usando el access_token para obtener info del negocio
        url = f"{settings.meta_whatsapp_api_url}/{settings.meta_whatsapp_phone_number_id}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                params={"fields": "verified_name"},
                headers={"Authorization": f"Bearer {settings.meta_whatsapp_access_token}"}
            )
            resp.raise_for_status()
        return {"status": "ok", "details": "Conectado"}
    except Exception as e:
        logger.error(f"Meta WhatsApp health check failed: {e}")
        return {"status": "error", "details": str(e)}


async def check_r2() -> dict[str, str]:
    try:
        def _check():
            client = get_r2_client()
            client.head_bucket(Bucket=settings.r2_bucket_name)
        
        await asyncio.to_thread(_check)
        return {"status": "ok", "details": "Conectado"}
    except Exception as e:
        logger.error(f"Cloudflare R2 health check failed: {e}")
        return {"status": "error", "details": str(e)}


@router.get("/integrations-health", dependencies=[RequireAdmin])
async def integrations_health() -> dict[str, Any]:
    """Verifica el estado de las integraciones externas usando las credenciales reales."""
    results = await asyncio.gather(
        check_twilio(),
        check_elevenlabs(),
        check_meta_whatsapp(),
        check_r2(),
    )
    
    return {
        "twilio": results[0],
        "elevenlabs": results[1],
        "meta": results[2],
        "cloudflare_r2": results[3],
    }
