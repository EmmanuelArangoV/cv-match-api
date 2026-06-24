import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase
from src.config import settings
from src.infrastructure.db.database import get_db

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _verify_meta_signature(payload: bytes, signature_header: str | None) -> bool:
    """Valida la firma HMAC-SHA256 que Meta incluye en X-Hub-Signature-256."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.meta_whatsapp_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request) -> Response:
    """Meta llama a este endpoint para verificar el webhook al configurarlo."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.meta_whatsapp_verify_token:
        return Response(content=challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@router.post("/whatsapp")
async def receive_whatsapp_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recibe mensajes entrantes de WhatsApp validando firma HMAC de Meta."""
    raw_body = await request.body()

    if not _verify_meta_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="Firma HMAC inválida")

    body = await request.json()

    if body.get("object") != "whatsapp_business_account":
        raise HTTPException(status_code=404, detail="No es un evento de WhatsApp")

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" not in value:
                continue
            for message in value["messages"]:
                if message.get("type") != "text":
                    continue
                from_phone = message.get("from")
                message_text = message.get("text", {}).get("body", "")
                if from_phone and message_text:
                    use_case = ProcessWhatsAppMessageUseCase(db)
                    await use_case.execute(from_phone, message_text)

    return {"status": "ok"}
