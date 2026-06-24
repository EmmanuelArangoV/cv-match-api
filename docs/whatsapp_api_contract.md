# WhatsApp Integration - Summary & API Contract

Este documento resume la arquitectura y los contratos de datos establecidos durante la integración de WhatsApp Business y OpenAI para **Riwi Match**.

## 1. Resumen de lo Desarrollado
Durante esta sesión logramos completar el flujo End-to-End de comunicación automatizada con los candidatos:
- **Disparador Automático:** Al finalizar el procesamiento de la Hoja de Vida (`parse_cv`), Celery automáticamente delega a una nueva tarea asíncrona (`send_whatsapp_consent`) el envío de la plantilla inicial de WhatsApp.
- **Base de Datos Sincronizada:** Generamos y aplicamos migraciones de Alembic para soportar los nuevos campos de estado de WhatsApp en `ProcessCandidate` (`whatsapp_consent_status`, `whatsapp_responded_at`).
- **Scripts de Pruebas:** Se construyó un script aislado (`scripts/test_whatsapp.py`) que permite simular la creación de candidatos y el envío de plantillas sin necesidad de cargar CVs o arrancar Celery.
- **Webhook Configurado:** Habilitamos la recepción de mensajes (Respuestas del candidato) a través de un Webhook verificado por Meta.
- **IA Bidireccional:** Las respuestas entrantes son analizadas por OpenAI para comprender el _intent_ (aceptación, rechazo o preguntas) y emitir un mensaje de respuesta contextual en tiempo real.

---

## 2. API Contract: Webhook de Meta

### 2.1. Validación del Webhook (GET)
Meta verifica la propiedad del webhook enviando un desafío `GET`.

**Endpoint:** `GET /api/v1/webhooks/whatsapp`

**Query Parameters:**
| Parámetro | Tipo | Descripción |
| :--- | :--- | :--- |
| `hub.mode` | `string` | Siempre es `"subscribe"` |
| `hub.challenge` | `integer` | Número aleatorio que debe ser devuelto |
| `hub.verify_token` | `string` | Token secreto (`META_WHATSAPP_VERIFY_TOKEN`) |

**Respuesta Exitosa (200 OK):**
Devuelve el `hub.challenge` en texto plano (Text/Plain).

---

### 2.2. Recepción de Mensajes (POST)
Cuando el candidato responde en WhatsApp, Meta envía un POST a nuestro servidor.

**Endpoint:** `POST /api/v1/webhooks/whatsapp`

**Body (JSON) - Estructura Simplificada de Meta:**
```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "1234567890",
              "phone_number_id": "1180119558517396"
            },
            "contacts": [
              {
                "profile": { "name": "Nombre del Candidato" },
                "wa_id": "573185926525"
              }
            ],
            "messages": [
              {
                "from": "573185926525",
                "id": "wamid.HBgLNTczMT...",
                "timestamp": "1719253456",
                "type": "text",
                "text": {
                  "body": "Hola, sí me interesa la entrevista."
                }
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}
```

---

## 3. Worker Tasks (Celery)

### Tarea: `send_whatsapp_consent`
- **Ubicación:** `src/infrastructure/workers/tasks/whatsapp.py`
- **Responsabilidad:** Enviar la primera plantilla ("consentimiento_entrevista" o "hello_world") al teléfono del candidato.
- **Payload esperado:** 
  ```python
  process_candidate_id: str # UUID del ProcessCandidate
  ```
- **Disparador:** Al finalizar la tarea `parse_cv`.

---

## 4. Requisitos de Infraestructura (Variables de Entorno)
Para que el entorno funcione, es estrictamente necesario definir:
- `META_WHATSAPP_API_URL`
- `META_WHATSAPP_PHONE_NUMBER_ID`
- `META_WHATSAPP_ACCESS_TOKEN` (Token de Meta)
- `META_WHATSAPP_VERIFY_TOKEN` (Para validación del webhook)
- Base de datos en Postgres y Broker de Celery (Redis) en ejecución.
