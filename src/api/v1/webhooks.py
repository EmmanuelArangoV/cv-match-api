import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase
from src.config import settings
from src.infrastructure.db.database import get_db

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _verify_meta_signature(payload: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.meta_whatsapp_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _extract_message_content(message: dict) -> tuple[str, str]:
    """
    Extrae (from_phone, text) de cualquier tipo de mensaje de WhatsApp.

    Tipos que manejamos:
    - text            → mensaje de texto libre del candidato
    - interactive     → clic en botón de la plantilla (button_reply)
    """
    from_phone = message.get("from", "")
    msg_type = message.get("type", "")

    if msg_type == "text":
        return from_phone, message.get("text", {}).get("body", "")

    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        if interactive.get("type") == "button_reply":
            # El candidato hizo clic en "Sí, acepto" o "No, gracias"
            return from_phone, interactive["button_reply"]["title"]

    return from_phone, ""


@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request) -> Response:
    """Meta llama aquí para verificar el webhook al configurarlo."""
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
    """Recibe mensajes y clics de botón de WhatsApp, valida firma HMAC de Meta."""
    raw_body = await request.body()

    if not _verify_meta_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="Firma HMAC inválida")

    body = await request.json()

    if body.get("object") != "whatsapp_business_account":
        raise HTTPException(status_code=404, detail="No es un evento de WhatsApp")

    use_case = ProcessWhatsAppMessageUseCase(db)

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" not in value:
                continue
            for message in value["messages"]:
                from_phone, text = _extract_message_content(message)
                if from_phone and text:
                    await use_case.execute(from_phone, text)

    return {"status": "ok"}
