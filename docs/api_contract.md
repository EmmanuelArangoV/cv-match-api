# Contrato API — resumen vigente

> Actualizado: 2026-08-09. La fuente de verdad exacta es el OpenAPI generado por la versión que
> está corriendo: `GET /openapi.json` y Swagger en `GET /docs`. Este documento explica alcance y
> reglas; no duplica todos los schemas para evitar divergencias.

La API usa prefijo `/api/v1`, JSON salvo uploads/descargas y JWT Bearer. Las excepciones de dominio
se traducen de forma uniforme a 400/401/404/409/422. Roles y ownership se validan en backend aunque
el frontend oculte acciones.

## Dominios montados

| Dominio | Rutas principales | Notas |
| --- | --- | --- |
| Auth/usuarios | `/auth/*`, `/users/*`, `/system/*` | Login, refresh, logout, perfil, CRUD/estado por rol |
| Inicio | `/processes/home`, `/processes/home/options`, `/metrics/home` | Paginación, búsqueda, filtros y agregados server-side |
| Procesos/JD | `/processes/*` | CRUD, status, JD texto/archivo/versiones, prompts y plantilla WhatsApp |
| Candidatos | `/processes/{id}/candidates/*` | Upload, análisis manual, detalle, descarte/restauración y disponibilidad |
| Match | `/processes/{id}/match*` | Ejecución manual, progreso, ranking y override humano |
| Question Sets | `/question-sets/*` | Versiones, preguntas y criterios; no contienen prompts |
| Profiling | `/profiling/*` | Board, runs, detalle, audio, cancelación, retry/override |
| IA/plantillas | `/ai-config/*`, `/whatsapp-templates` | Config global Admin y selección de plantillas disponibles |
| Operación | `/metrics/*`, `/reports/*`, `/audit/*`, `/search/*`, `/notifications/*`, `/feedback/*` | Agregados, CSV, trazabilidad y utilidades |
| Webhooks | `/webhooks/whatsapp`, `/webhooks/twilio/*`, `/webhooks/elevenlabs/*` | Verificación, estados, AMD, TwiML y post-call |

## Home optimizado

`GET /processes/home` devuelve solo la proyección necesaria para tarjetas/listado, más metadata de
paginación. Acepta búsqueda y filtros de etapa, recruiter y área. Cerrados/archivados no aparecen
por defecto, pero deben poder solicitarse expresamente. No sustituir este endpoint con un listado
completo seguido de N llamadas de detalle.

`GET /processes/home/options` entrega opciones de filtro y `GET /metrics/home` los agregados que la
pantalla necesita. El frontend debe mantener los filtros en el request y no recalcular totales con
una sola página.

## Análisis y match

La carga no analiza automáticamente. El endpoint de análisis solo toma candidatos `LOADED` o
`CV_ERROR`; al terminar quedan disponibles para match. El match se dispara aparte. Ambos son
asíncronos e idempotentes frente a reintentos esperados; la UI consulta progreso.

## Prompts

- `/ai-config/prompts/*`: plantillas globales administradas por Admin.
- `/processes/{process_id}/ai-prompts`: únicamente comunicación por proceso.
- Tipos globales: `CV_EXTRACTION`, `CV_MATCH`, `JD_ENHANCEMENT`, `VOICE_PROFILING`.
- Tipos de proceso: `WHATSAPP_MESSAGE`, `VOICE_CALL_AGENT`.
- El payload de voz contiene `first_message` y contenido del agente. Question Set no aporta un
  prompt heredado ni `default_first_message`.

## Plantillas WhatsApp

Admin crea/sincroniza/habilita/marca default mediante `/ai-config/whatsapp-templates`. Recruiters
consultan las opciones aprobadas/habilitadas en `/whatsapp-templates` y asignan una al proceso en
`/processes/{process_id}/whatsapp-template`. El inicio de profiling valida que la selección siga
siendo utilizable.

## Profiling y webhooks

Cada intento tiene `run_id`. Antes de publicar una llamada se persiste el run y se impide más de
uno activo por candidato. La correlación conserva `run_id`, `CallSid` y conversación ElevenLabs.
El webhook async AMD puede terminar la llamada si Twilio confirma máquina/fax. Los webhooks de
estado y post-call deben ser idempotentes porque los proveedores reintentan.

## Archivos y exports

Las descargas protegidas pueden responder con redirect firmado de R2 o stream. El frontend usa su
proxy BFF `/dl/*` para adjuntar el JWT httpOnly; no debe poner tokens en query strings.

## Errores y compatibilidad

- No asumir que una clave opcional llegará como `null`: algunos schemas la omiten.
- Tratar UUID, enums y timestamps conforme al OpenAPI actual.
- Un `202` indica trabajo encolado, no completado.
- Un `/health` exitoso no valida proveedores; `/ready` y una prueba específica aportan evidencia
  adicional.

Para congelar un contrato de release, exporta el OpenAPI del commit desplegado y versiona ese
artefacto junto al cliente; no copies a mano cientos de campos a este resumen.
