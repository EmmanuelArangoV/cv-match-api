from fastapi import APIRouter, Request, Response, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import settings
from src.infrastructure.db.database import get_db
from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    """
    Endpoint para que Meta WhatsApp Business verifique el webhook (hub.challenge).
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == settings.meta_whatsapp_verify_token:
            return Response(content=challenge, status_code=200)
        print(f"WEBHOOK ERROR: Received token='{token}', Expected='{settings.meta_whatsapp_verify_token}'")
        raise HTTPException(status_code=403, detail="Verification token mismatch")
    raise HTTPException(status_code=400, detail="Missing parameters")

@router.post("/whatsapp")
async def receive_whatsapp_message(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Recibe los mensajes entrantes de WhatsApp.
    """
    body = await request.json()
    
    # Valida si es un evento de mensaje de WhatsApp
    if body.get("object") == "whatsapp_business_account":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # Ignorar statuses de envío/lectura, procesar solo mensajes
                if "messages" in value:
                    for message in value["messages"]:
                        from_phone = message.get("from")
                        message_text = message.get("text", {}).get("body", "")
                        
                        # Procesar la respuesta con la IA
                        use_case = ProcessWhatsAppMessageUseCase(db)
                        await use_case.execute(from_phone, message_text)
                        
                        print(f"Mensaje procesado de {from_phone}: {message_text}")
                        
        return {"status": "ok"}
    
    raise HTTPException(status_code=404, detail="Not a WhatsApp event")
