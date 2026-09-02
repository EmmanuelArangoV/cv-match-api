---
sidebar_position: 7
---

# Seguimiento y conciliación de costos

El costo no se estima en el navegador. Cada operación cobrable crea un `CostLog` en PostgreSQL y
el backend agrega esas filas para procesos, candidatos, recruiters y dashboards. El objetivo es
mantener trazabilidad por proveedor y evitar que un reintento, webhook repetido o doble clic cobre
dos veces en los reportes.

## El registro auditable

`src/infrastructure/db/models.py` define `CostLog`. Cada fila conserva:

| Campo | Uso |
| --- | --- |
| `process_id`, `candidate_id`, `user_id` | Atribución a proceso, persona y recruiter cuando aplica. |
| `operation_type`, `provider`, `model_used` | Qué se ejecutó y con qué proveedor/modelo. |
| Tokens y `call_duration_s` | Unidades medibles de IA y telefonía. |
| `estimated_cost`, `currency`, `cost_source` | Importe en USD y su procedencia. |
| `external_reference` | Identificador único del proveedor o del intento; evita duplicados. |
| `cost_breakdown` | JSONB con tarifas, unidades y detalles para auditoría. |

`record_cost_async` y `record_cost_sync` usan un insert idempotente por `external_reference`. Si
el callback se entrega de nuevo, no debe crear una segunda fila. Una referencia ausente solo es
aceptable cuando la operación no ofrece un identificador externo y se construye una referencia
estable desde el intento de tarea.

## Recorrido por operación

| Operación | Origen de la ejecución | Proveedor y fuente de costo | Referencia de conciliación |
| --- | --- | --- | --- |
| `CV_STORAGE` | Carga de CV. | R2, tarifa pública de almacenamiento/operación. | Clave de objeto y hash de archivo. |
| `CV_EXTRACTION` y `CV_EMBEDDING` | Tarea `parse_cv`. | OpenAI, uso de tokens y rate card. | ID de respuesta o ID de tarea/reintento. |
| `CV_MATCH` | Tarea `run_match`. | OpenAI, uso de tokens y rate card. | ID de respuesta de proveedor. |
| `JD_ENHANCEMENT` | Caso de uso de JD. | OpenAI, uso de tokens y rate card. | ID de respuesta de proveedor. |
| `WHATSAPP_MESSAGE` | Tarea de consentimiento. | Meta, rate card de plantilla/categoría. | ID del mensaje de Meta. |
| `WHATSAPP_AI` | Generación de mensaje cuando corresponde. | OpenAI, uso de tokens y rate card. | ID de respuesta de proveedor. |
| `TWILIO_CALL` | Webhook de estado final de Twilio. | Importe reportado del Call Resource, más AMD/Media Stream por tarifa si aplica. | `CallSid`. |
| `VOICE_CALL` | Webhook post-call de ElevenLabs. | `cost_fiat` reportado; fallback de créditos solo para payloads antiguos. | ID de conversación. |
| `ANSWER_EVALUATION` y `VOICE_TRANSCRIPTION` | Evaluación posterior del profiling. | OpenAI, uso de tokens y rate card. | ID de respuesta de proveedor. |

Los nombres exactos están en `OperationType`; no se debe crear una categoría textual paralela en
frontend, reportes o scripts.

## Estimado, reportado y conciliado

`estimated_cost` conserva un nombre histórico: no significa que toda fila sea una suposición.
`cost_source` lo explica:

- `*_reported` o `*_call_resource`: importe recibido del proveedor.
- `*_rate_card`: cálculo reproducible con una tarifa registrada en
  `src/infrastructure/costs.py`.
- una fuente mixta, como `twilio_reported_plus_rate_card`, conserva ambas partes en
  `cost_breakdown`.
- los fallbacks se mantienen visibles; no se hacen pasar por valores reportados.

Al cambiar modelo, precio, país/categoría de Meta o proveedor, primero actualiza la tarifa y sus
pruebas numéricas; después ejecuta una operación real autorizada, compara el dashboard del
proveedor con el `CostLog` y anota fecha/fuente de la conciliación. Una compilación o un mock no
valida un precio real.

## Presupuestos y alertas

Cada proceso puede tener `budget_max_usd`. Los casos de uso que disparan operaciones costosas
consultan el acumulado antes de continuar; al agotarse, la regla de dominio bloquea nuevas
ejecuciones. `check_and_notify_budget_sync` crea una sola notificación por umbral de 50 %, 80 % y
100 % para cada proceso.

La pantalla global permite configurar un límite de visualización de plataforma. No lo confundas
con el guard de negocio por proceso: el bloqueo efectivo de una operación depende de
`budget_max_usd` y del caso de uso que la inicia.

## Lectura en API y frontend

| Necesidad | Contrato backend | Consumo frontend |
| --- | --- | --- |
| Tendencia corta de Inicio | `GET /api/v1/metrics/home` | `getHomeMetrics`. |
| Agregados globales o por proceso | `GET /api/v1/metrics/dashboard` | `getDashboardMetrics` y `getProcessDashboardMetrics`. |
| Resumen de un proceso | `GET /api/v1/processes/{id}/metrics` | Vista del proceso. |
| Costos por candidato | `GET /api/v1/processes/{id}/candidates/{pc_id}` | Detalle de candidato. |
| Exportación | `GET /api/v1/processes/{id}/export/costs` | Proxy BFF `/dl/*`. |
| Tablero financiero | Agregados anteriores | Ruta `/app/costos`. |

La UI agrupa y visualiza. No recalcula precios de proveedor, no deriva totales de una página
paginada y no inventa datos faltantes.

## Rutina de seguimiento

1. Revisa total, tendencia y desglose por proceso/operación en `/app/costos`.
2. Ante un salto, filtra el proceso y abre el detalle del candidato o exporta el CSV.
3. Agrupa por `provider`, `operation_type`, `external_reference` y `cost_source`; busca referencias
   nulas o duplicadas antes de modificar una tarifa.
4. Contrasta una muestra contra la factura/dashboard del proveedor. Marca claramente si el valor es
   `reported`, `rate_card` o fallback.
5. Revisa alertas de presupuesto y confirma que la siguiente acción costosa queda bloqueada cuando
   el proceso ya excedió su límite.
6. Después de una prueba real autorizada, limpia los datos QA según el procedimiento del ambiente y
   conserva solo la evidencia de conciliación que no exponga CVs, teléfonos ni tokens.

## Límites de la evidencia actual

La estructura, idempotencia, agregados y UI están implementados. La exactitud de una integración
de costos solo queda validada por una prueba real con la credencial y el proveedor correspondiente.
Por eso se debe reportar por separado: pruebas unitarias, E2E con mock, healthcheck y conciliación
real de facturación.
