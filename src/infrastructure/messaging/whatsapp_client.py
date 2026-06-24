import httpx
from src.config import settings

class WhatsAppClient:
    def __init__(self) -> None:
        self.base_url = f"{settings.meta_whatsapp_api_url}/{settings.meta_whatsapp_phone_number_id}"
        self.headers = {
            "Authorization": f"Bearer {settings.meta_whatsapp_access_token}",
            "Content-Type": "application/json",
        }

    async def send_template_message(self, to_phone: str, template_name: str, language_code: str = "es") -> dict:
        """
        Envía un mensaje de plantilla de WhatsApp.
        """
        url = f"{self.base_url}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                }
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=self.headers, json=payload)
            if response.status_code >= 400:
                print(f"Error de Meta: {response.text}")
            response.raise_for_status()
            return response.json()

    async def send_text_message(self, to_phone: str, message: str) -> dict:
        """
        Envía un mensaje de texto plano (requiere ventana de 24h abierta).
        """
        url = f"{self.base_url}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()

whatsapp_client = WhatsAppClient()
