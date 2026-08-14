# WhatsApp y plantillas — contrato operativo

> Actualizado: 2026-08-09. Los schemas exactos están en `/openapi.json`.

## Responsabilidades

Admin administra el catálogo de `WhatsAppTemplate`: nombre registrado en Meta, idioma, categoría,
componentes/botones, estado Meta, habilitación interna y plantilla predeterminada. Puede crear,
enviar, sincronizar y mapear plantillas. Recruiter solo elige entre plantillas aprobadas y
habilitadas para un proceso.

La asignación del proceso es explícita. El system prompt `WHATSAPP_MESSAGE` define comportamiento
contextual, pero no reemplaza el contenido oficial aprobado por Meta.

## Endpoints de aplicación

- Admin: `/api/v1/ai-config/whatsapp-templates/*`.
- Opciones para recruiter: `GET /api/v1/whatsapp-templates`.
- Asignación: `PATCH /api/v1/processes/{process_id}/whatsapp-template`.
- Webhook Meta: `GET|POST /api/v1/webhooks/whatsapp`.

Los paths/verbos específicos de cada operación se consultan en OpenAPI.

## Flujo de consentimiento

1. El recruiter selecciona candidatos y dispara profiling.
2. El backend valida proceso, teléfono y una plantilla aprobada/habilitada.
3. Celery envía la plantilla y solo marca el consentimiento como enviado si Meta aceptó el envío.
4. Meta entrega mensajes, respuestas interactivas y estados al webhook.
5. Los botones configurados se interpretan como aceptación/rechazo; texto libre usa la política de
   intención vigente sin convertir respuestas ambiguas en consentimiento.
6. Al aceptar se encola el profiling respetando delay/concurrencia. Rechazo/timeout cancelan el
   intento según lifecycle.

Reintentar un profiling pendiente puede reenviar el consentimiento; el handler debe ser idempotente
ante webhooks duplicados.

## Verificación del webhook

`GET /api/v1/webhooks/whatsapp` valida `hub.mode`, `hub.verify_token` y devuelve
`hub.challenge`. `POST` recibe la envoltura oficial de WhatsApp Business. En ambientes no locales,
verifica la firma con `META_WHATSAPP_WEBHOOK_SECRET`; no documentes ni registres el secreto.

El webhook también procesa cambios de estado de plantillas y mensajes. Debe tolerar lotes,
eventos desconocidos y reintentos sin duplicar transiciones ni costos.

## Variables

```text
META_WHATSAPP_API_URL
META_WHATSAPP_BUSINESS_ACCOUNT_ID
META_WHATSAPP_PHONE_NUMBER_ID
META_WHATSAPP_ACCESS_TOKEN
META_WHATSAPP_VERIFY_TOKEN
META_WHATSAPP_WEBHOOK_SECRET
WHATSAPP_TEMPLATE_FALLBACK_ENABLED
PUBLIC_BASE_URL
```

`PUBLIC_BASE_URL` debe ser HTTPS alcanzable por Meta. En local usa ngrok y sigue
`../../.agents/skills/start-project/SKILL.md`.

## Costos y privacidad

Cada envío cobrable registra un `CostLog` idempotente con fuente de costo. No guardar tokens ni el
payload completo del candidato en logs. Las pruebas reales requieren un número autorizado y una
decisión explícita sobre conservar o limpiar sus datos.
