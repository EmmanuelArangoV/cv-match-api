from __future__ import annotations

import re
from typing import Any

import httpx

from src.config import settings
from src.domain.shared.exceptions import BusinessRuleException

SUPPORTED_TEMPLATE_BINDINGS = {
    "candidate_name",
    "job_title",
    "process_name",
    "recruiter_name",
}
_BODY_PLACEHOLDER_RE = re.compile(r"\{\{(\d+)\}\}")


def template_bindings_are_valid(
    components: list[dict[str, Any]], variable_bindings: dict[str, Any]
) -> bool:
    """Comprueba que cada variable BODY de Meta tenga un único dato local soportado."""
    body_text = next(
        (
            str(component.get("text") or "")
            for component in components
            if str(component.get("type") or "").upper() == "BODY"
        ),
        "",
    )
    expected_positions = {
        str(int(position)) for position in _BODY_PLACEHOLDER_RE.findall(body_text)
    }
    body_bindings = variable_bindings.get("BODY") or {}
    if not isinstance(body_bindings, dict):
        return False
    normalized_bindings = {str(position): key for position, key in body_bindings.items()}
    return set(normalized_bindings) == expected_positions and all(
        key in SUPPORTED_TEMPLATE_BINDINGS for key in normalized_bindings.values()
    )


class WhatsAppClient:
    def __init__(self) -> None:
        self._base_url = (
            f"{settings.meta_whatsapp_api_url}/{settings.meta_whatsapp_phone_number_id}"
        )
        self._headers = {
            "Authorization": f"Bearer {settings.meta_whatsapp_access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _meta_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
            error = payload.get("error") or {}
            return str(error.get("error_user_msg") or error.get("message") or response.text)
        except Exception:
            return response.text or f"HTTP {response.status_code}"

    async def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Crea una plantilla en el WABA y la deja en revisión de Meta."""
        if not settings.meta_whatsapp_business_account_id:
            raise BusinessRuleException(
                "Configura META_WHATSAPP_BUSINESS_ACCOUNT_ID para administrar plantillas."
            )
        url = (
            f"{settings.meta_whatsapp_api_url}/"
            f"{settings.meta_whatsapp_business_account_id}/message_templates"
        )
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=self._headers, json=payload)
        if response.is_error:
            raise BusinessRuleException(
                f"Meta rechazó la creación de la plantilla: {self._meta_error(response)}"
            )
        return dict(response.json())

    async def list_templates(self) -> list[dict[str, Any]]:
        """Lista todas las plantillas del WABA, recorriendo la paginación de Graph API."""
        if not settings.meta_whatsapp_business_account_id:
            raise BusinessRuleException(
                "Configura META_WHATSAPP_BUSINESS_ACCOUNT_ID para sincronizar plantillas."
            )
        url: str | None = (
            f"{settings.meta_whatsapp_api_url}/"
            f"{settings.meta_whatsapp_business_account_id}/message_templates"
        )
        params: dict[str, str] | None = {
            "fields": (
                "id,name,language,status,category,components,rejected_reason,last_updated_time"
            ),
            "limit": "100",
        }
        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20) as client:
            while url:
                response = await client.get(url, headers=self._headers, params=params)
                if response.is_error:
                    raise BusinessRuleException(
                        f"No se pudieron sincronizar las plantillas de Meta: "
                        f"{self._meta_error(response)}"
                    )
                payload = response.json()
                rows.extend(payload.get("data") or [])
                url = (payload.get("paging") or {}).get("next")
                params = None
        return rows

    @staticmethod
    def build_template_components(
        variable_bindings: dict[str, Any], context: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Convierte el mapeo local BODY/{{n}} al payload posicional exigido por Meta."""
        body_bindings = variable_bindings.get("BODY") or {}
        if not body_bindings:
            return []
        try:
            positions = sorted((int(position), key) for position, key in body_bindings.items())
        except (TypeError, ValueError) as exc:
            raise BusinessRuleException("El mapeo de variables de WhatsApp es inválido.") from exc
        if [position for position, _ in positions] != list(range(1, len(positions) + 1)):
            raise BusinessRuleException(
                "Las variables de WhatsApp deben ser consecutivas desde {{1}}."
            )
        parameters: list[dict[str, str]] = []
        for _, key in positions:
            if key not in SUPPORTED_TEMPLATE_BINDINGS:
                raise BusinessRuleException(f"Variable de WhatsApp no soportada: {key}.")
            value = str(context.get(key) or "").strip()
            if not value:
                raise BusinessRuleException(
                    f"No se pudo resolver la variable de WhatsApp '{key}'."
                )
            parameters.append({"type": "text", "text": value})
        return [{"type": "body", "parameters": parameters}]

    async def send_consent_template(
        self,
        to_phone: str,
        *,
        template_name: str,
        language: str,
        variable_bindings: dict[str, Any],
        context: dict[str, str],
    ) -> dict[str, Any]:
        """
        Envía la plantilla aprobada elegida en el proceso. El fallback hello_world solo existe
        para desarrollo explícito y nunca sustituye una selección en staging/producción.
        """
        template: dict[str, Any]
        if settings.whatsapp_template_fallback_enabled and settings.app_env == "development":
            template = {"name": "hello_world", "language": {"code": "en_US"}}
        else:
            template = {
                "name": template_name,
                "language": {"policy": "deterministic", "code": language},
            }
            components = self.build_template_components(variable_bindings, context)
            if components:
                template["components"] = components

        digits_only = re.sub(r"\D", "", to_phone)
        formatted_phone = f"+{digits_only}" if digits_only else to_phone

        payload = {
            "messaging_product": "whatsapp",
            "to": formatted_phone,
            "type": "template",
            "template": template,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self._base_url + "/messages", headers=self._headers, json=payload
            )
            response.raise_for_status()
            return dict(response.json())

    async def send_text_message(self, to_phone: str, message: str) -> dict[str, Any]:
        """Envía texto libre dentro de la ventana de 24h."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self._base_url + "/messages", headers=self._headers, json=payload
            )
            response.raise_for_status()
            return dict(response.json())

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
