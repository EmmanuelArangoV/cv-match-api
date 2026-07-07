import httpx

from src.config import settings


class WhatsAppClient:
    def __init__(self) -> None:
        self._base_url = (
            f"{settings.meta_whatsapp_api_url}/{settings.meta_whatsapp_phone_number_id}"
        )
        self._headers = {
            "Authorization": f"Bearer {settings.meta_whatsapp_access_token}",
            "Content-Type": "application/json",
        }

    async def send_consent_template(
        self,
        to_phone: str,
        candidate_name: str,
        job_title: str = "",
    ) -> dict:
        """
        Envía la plantilla de consentimiento aprobada por Meta.
        Nombre en Meta Business: 'autorizacion_llamada_ia_v2'
        Variables: {{1}} = nombre candidato

        Mientras Meta no haya aprobado la plantilla, si
        WHATSAPP_TEMPLATE_FALLBACK_ENABLED=true en el .env, se envía en su
        lugar 'hello_world' (plantilla de muestra que Meta aprueba
        automáticamente en toda cuenta) para poder probar el resto del flujo
        (webhook + agente de IA) sin quedar bloqueados por la revisión.
        """
        if settings.whatsapp_template_fallback_enabled:
            template = {"name": "hello_world", "language": {"code": "en_US"}}
        else:
            template = {
                "name": "autorizacion_llamada_ia_v2",
                "language": {"code": "es_CO"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": candidate_name},
                        ],
                    }
                ],
            }

        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": template,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self._base_url + "/messages", headers=self._headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def send_text_message(self, to_phone: str, message: str) -> dict:
        """Envía texto libre (válido dentro de la ventana de 24h después de que el candidato escribió)."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self._base_url + "/messages", headers=self._headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def mark_as_read(self, message_id: str) -> None:
        """Marca el mensaje del candidato como leído (muestra los dos checks azules)."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(self._base_url + "/messages", headers=self._headers, json=payload)


whatsapp_client = WhatsAppClient()
